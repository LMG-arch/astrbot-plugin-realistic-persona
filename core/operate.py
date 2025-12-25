import time

from astrbot.api import logger
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from astrbot.core.star.context import Context

from .comment import Comment
from .llm_action import LLMAction
from .post import Post, PostDB
from .qzone_api import Qzone
from .utils import get_ats, get_nickname


class PostOperator:
    def __init__(
        self,
        context: Context,
        config: AstrBotConfig,
        qzone: Qzone,
        db: PostDB,
        llm: LLMAction,
        style,
    ):
        self.context = context
        self.config = config
        self.qzone = qzone
        self.db = db
        self.llm = llm
        self.style = style
        self.uin = 0
        self.name = "我"
        # 获取唯一管理员
        self.admin_ids: list[str] = context.get_config().get("admins_id", [])
        self.admin_id = next(aid for aid in self.admin_ids if aid.isdigit())
        
        # 人设配置（优先使用插件配置）
        self.persona_profile = config.get("persona_profile", "")
    
    async def _get_persona_profile(self) -> str:
        """
        获取人设配置，优先使用插件配置，其次使用系统人设
        
        Returns:
            人设描述文本
        """
        # 1. 优先使用插件自己的人设配置
        if self.persona_profile and self.persona_profile.strip():
            logger.debug("[PostOperator] 使用插件配置的人设")
            return self.persona_profile.strip()
        
        # 2. 回退到系统人设
        try:
            persona_mgr = self.context.persona_manager
            default_persona = await persona_mgr.get_default_persona_v3()
            system_profile = default_persona.get("prompt", "")
            if system_profile:
                logger.debug("[PostOperator] 使用系统配置的人设")
                return system_profile
        except Exception as e:
            logger.debug(f"[PostOperator] 获取系统人设失败: {e}")
        
        # 3. 都没有则返回空
        logger.debug("[PostOperator] 未配置人设，使用空字符串")
        return ""

    # ------------------------ 公共 pipeline ------------------------ #
    async def _pipeline(
        self,
        event: AiocqhttpMessageEvent | None,
        get_recent: bool = False,
        get_sender: bool = False,
        no_self: bool = False,
        no_commented: bool = False,
        send_error: bool = True,
    ) -> list[Post]:
        """
        管道：取说说 → 解析参数 → 过滤 → 补详情 → 落库
        """
        # 解析目标用户
        target_id = ""
        if event:
            if at_ids := get_ats(event):
                target_id = at_ids[0]
            else:
                target_id = event.get_sender_id() if get_sender else event.get_self_id()
        else:
            target_id = str(self.qzone.ctx.uin)

        if not target_id:
            logger.error("获取不到用户ID")
            return []

        if int(target_id) in self.config["ignore_users"]:  # 忽略用户
            logger.warning(f"已忽略用户（{target_id}）的QQ空间")
            return []

        posts: list[Post] = []

        # 解析范围参数
        pos, num = 0, 1  # 默认值
        if event:
            end_parm = event.message_str.strip().split()[-1]
            if "~" in end_parm:
                try:
                    start_str, end_str = end_parm.split("~", 1)
                    start_index, end_index = int(start_str), int(end_str)
                    if start_index <= 0 or end_index < start_index:
                        raise ValueError("范围不合法")
                    pos = start_index - 1
                    num = end_index - start_index + 1
                except ValueError:
                    # 格式不对就回退到默认 1 条
                    pos, num = 0, 1
            elif end_parm.isdigit():
                pos = int(end_parm) - 1
                num = 1

        if get_recent:
            # 获取最新说说
            succ, data = await self.qzone.get_recent_feeds()
        else:
            # pos为开始位置， num为获取数量
            succ, data = await self.qzone.get_feeds(
                target_id=target_id, pos=pos, num=num
            )

        # 处理错误
        if not succ:
            logger.error(f"获取说说失败：{data}")
            if isinstance(data, dict):
                if code := data.get("code"):
                    if code in [-10031]:
                        self.config["ignore_users"].append(int(target_id))
                        logger.warning(
                            f"已将用户（{target_id}）添加到忽略列表，下次不再处理该用户的空间"
                        )
                        self.config.save_config()
                if event and send_error:
                    await event.send(
                        event.plain_result(data.get("message") or "获取不到说说")
                    )
                    event.stop_event()
            return []

        posts = data[pos : pos + num] if get_recent else data  # type: ignore

        # 过滤自己的说说
        self.uin = str(self.qzone.ctx.uin)
        if no_self:
            posts = [post for post in posts if str(post.uin) != self.uin]

        final_posts: list[Post] = []
        for post in posts:
            if no_commented:
                # 过滤已评论过的说说
                detail = await self.qzone.get_detail(post)
                if any(str(c.uin) == self.uin for c in detail.comments):
                    continue
                final_posts.append(detail)
            elif len(posts) == 1:
                # 单条说说则获取详情
                detail = await self.qzone.get_detail(post)
                final_posts.append(detail)
            else:
                # 多条说说则只获取基本信息
                final_posts.append(post)

        # 存到数据库
        for p in final_posts:
            await p.save(self.db)

        return final_posts

    async def view_feed(self, event: AiocqhttpMessageEvent, get_recent: bool = True):
        """
        查看说说 <序号/范围>
        Args:
            event (AiocqhttpMessageEvent): 事件对象
            get_recent (bool, optional): 是否获取最新说说. Defaults to True.
        """
        posts: list[Post] = await self._pipeline(event, get_recent=get_recent)
        for post in posts:
            img_path = await post.to_image(self.style)
            await event.send(event.image_result(img_path))

    async def read_feed(
        self,
        event: AiocqhttpMessageEvent | None = None,
        get_recent: bool = True,
        get_sender: bool = False,
        no_self=True,
        no_commented=True,
        send_error: bool = True,
        send_admin: bool = False,
    ):
        """
        读说说 <序号/范围> 即点赞+评论说说
        Args:
            event (AiocqhttpMessageEvent): 事件对象
            get_recent (bool): 是否获取最新说说
            get_sender (bool): 是否获取发送者
            no_self (bool): 是否过滤自己的说说
            no_commented (bool): 是否过滤已评论过的说说
            send_error (bool): 是否发送错误信息
            send_admin (bool): 是否仅发送消息给管理员
        """
        posts: list[Post] = await self._pipeline(
            event, get_recent, get_sender, no_self, no_commented, send_error
        )
        bot_name = (
            await get_nickname(event, event.get_self_id()) if event else self.name
        )

        logger.info(f"开始执行读说说任务, 共 {len(posts)} 条")

        like_succ = comment_succ = 0

        for idx, post in enumerate(posts, 1):
            if not post.tid:
                continue
            # -------------- 点赞 --------------
            try:
                like_ok, _ = await self.qzone.like(
                    tid=post.tid, target_id=str(post.uin)
                )
            except Exception as e:
                logger.warning(f"[{idx}] 点赞异常：{e}")
                like_ok = False
            if like_ok:
                like_succ += 1
                logger.info(f"[{idx}] 点赞成功 → {post.name}")

            # -------------- 评论 --------------
            try:
                content = await self.llm.generate_comment(post)
                if not content:
                    logger.error(f"[{idx}] 获取评论内容失败")
                    continue
                comment_ok, _ = await self.qzone.comment(
                    fid=post.tid,
                    target_id=str(post.uin),
                    content=content,
                )
                logger.info(f"[{idx}] 评论成功 → {post.name}")
            except Exception as e:
                logger.warning(f"[{idx}] 评论异常：{e}")
                comment_ok = False
            if comment_ok:
                comment_succ += 1
                # 落库
                comment = Comment(
                    uin=self.qzone.ctx.uin,
                    nickname=bot_name,
                    content=content, # type: ignore
                    create_time=int(time.time()),
                    tid=0,
                    parent_tid=None,
                )
                post.comments.append(comment)
                await post.save(self.db)
                # 可视化
                if event:
                    img_path = await post.to_image(self.style)
                    if send_admin:
                        event.message_obj.group_id = None # type: ignore
                        event.message_obj.sender.user_id = self.admin_id
                    await event.send(event.image_result(img_path))

        logger.info(f"执行完毕，点赞成功 {like_succ} 条，评论成功 {comment_succ} 条")

    async def publish_feed(
        self,
        event: AiocqhttpMessageEvent | None = None,
        text: str | None = None,
        images: list[str] | None = None,
        post: Post | None = None,
        publish: bool = True,
        llm_text: bool = False,
        llm_images: bool = False,
    ):
        """
        发说说封装
        Args:
            event (AiocqhttpMessageEvent): 事件
            text (str): 文本
            images (list[str]): 图片
            post (Post | None, optional): 原说说.
            publish (bool, optional): 是否发布.
            llm_text (bool, optional): 是否使用llm配文(仅在text为空时生效).
            llm_images (bool, optional): 是否使用llm配图(仅在images为空时生效).
        """
        # llm配文
        if llm_text and not text:
            persona_profile = await self._get_persona_profile()
            # 获取配置的用户ID
            user_id = self.config.get("diary_user_id", "")
            text = await self.llm.generate_diary(persona_profile=persona_profile, user_id=user_id)

        # llm配图：根据日记 + 生活信息构造提示词，用 ModelScope 生成图片
        # 根据用户偏好，如果设置了llm_images=True，则必须尝试生成配图
        if llm_images:
            diary_for_image = text
            if not diary_for_image:
                persona_profile = await self._get_persona_profile()
                # 获取配置的用户ID
                user_id = self.config.get("diary_user_id", "")
                diary_for_image = await self.llm.generate_diary(persona_profile=persona_profile, user_id=user_id)
            if diary_for_image:
                try:
                    # 获取配置的用户ID
                    user_id = self.config.get("diary_user_id", "")
                    logger.info(f"[配图] 配置的diary_user_id: {user_id}")
                    
                    # 获取群ID（如果event不为None）
                    group_id = ""
                    if event and hasattr(event, 'message_obj') and hasattr(event.message_obj, 'group_id'):
                        group_id = str(event.message_obj.group_id or "")
                        logger.info(f"[配图] 从 event 获取的group_id: {group_id}")
                    else:
                        logger.info(f"[配图] event为None或无group_id，使用user_id: {user_id}")
                    
                    # 传入group_id和user_id让大模型获取对话历史
                    img_prompt = await self.llm.generate_image_prompt_from_diary(
                        diary_for_image,
                        group_id=group_id,
                        user_id=user_id
                    )
                    if img_prompt:
                        img_url = await self.llm._request_image_with_fallback(img_prompt)
                        images = [img_url]
                        
                        # 如果没有文字内容，但有图片，可以使用日记内容作为文字
                        if not text and diary_for_image:
                            text = diary_for_image
                except Exception as e:
                    logger.error(f"LLM/图片生成失败：{e}", exc_info=True)
                    # 根据用户偏好，如果llm_images=True但图片生成失败，则不发布纯文本
                    if llm_images:
                        logger.warning("根据用户偏好，图片生成失败，将不发布说说")
                        return  # 直接返回，不发布说说
                    else:
                        logger.warning("图片生成失败，但llm_images=False，将继续发布")

        if not post:
            uin = event.get_self_id() if event else self.uin
            name = await get_nickname(event, uin) if event else self.name
            gin = (event.get_group_id() or 0) if event else 0
            post = Post(
                uin=int(uin),
                name=name,
                gin=int(gin),
                text=text or "",
                images=images or [],
                status="pending",
            )
            
            # 根据用户偏好，如果设置了llm_images=True但没有图片，则记录警告
            if llm_images and not (images and len(images) > 0):
                logger.warning("[自动发布说说] 根据配置应该生成配图，但配图生成失败或未生成")
        if publish:
            succ, data = await self.qzone.publish(post)
            if not succ:
                logger.error(f"发布说说失败：{str(data)}")
                if event:
                    await event.send(event.plain_result(str(data)))
                    event.stop_event()
                return  # 使用 return 而不是 raise StopIteration
            post.tid = data.get("tid", "")
            post.status = "approved"
            if now := data.get("now", ""):
                post.create_time = now
        # 落库
        await post.save(self.db)

        # 可视化
        if event:
            img_path = await post.to_image(self.style)
            await event.send(event.image_result(img_path))


    # async def reply_comment(self, event: AiocqhttpMessageEvent):
    #     """
    #     回复评论
    #     Args:
    #         event (AiocqhttpMessageEvent): 事件
    #     """
    #     post = await Post.get_by_tid(self.db, event.message_obj.message_id)
    #     comment = await Comment.get_by_tid(self.db, event.message_obj.message_id)
    #     reply_event_data = await get_reply_event_data(event)
    #     new_event = Event.from_payload(reply_event_data)
    #     if not new_event:
    #         logger.error(f"无法从回复消息数据构造 Event 对象: {reply_event_data}")
    #         return await event.send(event.plain_result("无法从回复消息数据构造 Event 对象"))
    #     abm_reply = await self._convert_handle_message_event(new_event, get_reply=False)
    #     if not abm_reply:
    #         logger.error(f"无法从回复消息数据构造 Event 响应对象: {reply_event_data}")
    #         return await event.send(event.plain_result("无法从回复消息数据构造 Event 响应对象"))
    #     reply_text = await self.llm.generate_comment(post, comment, abm_reply)
    #     reply_ok, _ = await self.qzone.comment(
    #         fid=post.tid,
    #         target_id=str(comment.uin),
    #         content=reply_text,
    #         parent_tid=comment.tid,
    #     )
    #     if not reply_ok:
    #         logger.error(f"回复评论失败")
    #         return await event.send(event.plain_result("回复评论失败"))
    #     comment = Comment(
    #         uin=self.qzone.ctx.uin,
    #         nickname=bot_name,
    #         content=reply_text,
    #         create_time=int(time.time()),
    #         tid=0,
    #         parent_tid=comment.tid,
    #     )
    #     post.comments.append(comment)
    #     await post.save(self.db)
    #     img_path = await post.to_image(self.style)
    #     await event.send(event.image_result(img_path))
    #     await self.update_dashboard(event)
    
    
    async def auto_reply_to_comments(self):
        """自动回复自己说说下的评论"""
        try:
            # 检查 Qzone 连接是否正常
            if not self.qzone:
                logger.warning("[自动回复] Qzone 对象未初始化，跳过自动回复")
                return
            
            # 检查 ctx 是否存在
            if not hasattr(self.qzone, 'ctx') or not self.qzone.ctx:
                logger.warning("[自动回复] Qzone.ctx 未连接或为 None，跳过自动回复")
                return
            
            # 检查 ctx.uin 是否存在
            if not hasattr(self.qzone.ctx, 'uin') or not self.qzone.ctx.uin:
                logger.warning("[自动回复] Qzone.ctx.uin 未初始化，跳过自动回复")
                return
            
            # 获取bot自己的说说列表
            succ, data = await self.qzone.get_feeds(
                target_id=str(self.qzone.ctx.uin),  # 获取自己的说说
                pos=0,  # 从第0条开始，而不是1
                num=10  # 检查最近10条说说
            )
            if not succ:
                logger.error("获取自己的说说列表失败")
                return
            
            bot_uin = str(self.qzone.ctx.uin)
            
            for post in data:
                if not post or not post.tid:  # 确保说说对象和ID存在
                    continue
                
                # 确认是bot自己的说说
                if str(post.uin) != bot_uin:
                    logger.debug(f"[自动回复] 跳过别人的说说: {post.tid}, 作者uin={post.uin}")
                    continue
                
                # 获取说说的详细信息(包含完整评论)
                detail = await self.qzone.get_detail(post)
                if not detail:
                    logger.warning(f"[自动回复] 无法获取说说详情: {post.tid}")
                    continue
                
                # 检查是否有新评论（未回复的）
                for comment in detail.comments:
                    # 1. 如果是别人对bot说说的评论
                    if str(comment.uin) == bot_uin:
                        logger.debug(f"[自动回复] 跳过自己的评论: {comment.content[:20]}...")
                        continue  # 不回复自己
                    
                    # 2. 如果是主评论(不是楼中楼)
                    if comment.parent_tid is None:
                        # 检查是否已经回复过（查看楼中楼是否有bot的回复）
                        has_replied = False
                        for sub_comment in detail.comments:
                            # 如果这个楼中楼是bot发的且父评论是当前评论
                            if (
                                sub_comment.parent_tid == comment.tid
                                and str(sub_comment.uin) == bot_uin
                            ):
                                has_replied = True
                                break
                        
                        if has_replied:
                            logger.debug(f"[自动回复] 已回复过评论 from {comment.nickname}: {comment.content[:20]}...")
                            continue
                        
                        # 生成回复内容
                        reply_text = await self.llm.generate_comment(post)
                        if not reply_text:
                            logger.warning(f"[自动回复] 生成回复内容失败")
                            continue
                        
                        # 使用reply API回复评论
                        reply_ok, result = await self.qzone.reply(
                            fid=str(post.tid),
                            target_name=comment.nickname,
                            content=reply_text
                        )
                        
                        if reply_ok:
                            logger.info(f"[自动回复] 成功回复评论 from {comment.nickname}: {reply_text[:50]}...")
                        else:
                            logger.error(f"[自动回复] 回复评论失败: {result}")
                    
        except Exception as e:
            logger.error(f"[自动回复] 发生错误: {e}", exc_info=True)
