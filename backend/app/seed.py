from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models import (
    Conversation,
    DocumentChunk,
    KnowledgeBase,
    KnowledgeAccess,
    KnowledgeDocument,
    Logistics,
    Order,
    OrderItem,
    Product,
    ServiceTicket,
    User,
)

DEMO_KNOWLEDGE_BASES: list[dict] = [
    {
        "name": "星云科技产品与售后知识库",
        "description": "面向客户与客服的产品参数、选购建议、配送、退换货、保修和发票规则",
        "documents": [
            {
                "filename": "产品目录与选购指南.md",
                "sections": [
                    (
                        "星云 X1 手机",
                        "星云 X1 手机配备 6.7 英寸高刷新率屏幕，支持 5G、无线充电和双卡双待。标准零售价 3999 元，适合重视影像、续航和移动办公的用户。",
                    ),
                    (
                        "云声 Air 2 耳机",
                        "云声 Air 2 是主动降噪真无线耳机，综合续航约 30 小时，支持通透模式和双设备连接。标准零售价 699 元，适合通勤、会议和日常音乐场景。",
                    ),
                    (
                        "极光 K87 机械键盘",
                        "极光 K87 采用 87 键布局，支持轴体热插拔、有线和无线连接。标准零售价 459 元，适合桌面空间有限且需要自定义手感的用户。",
                    ),
                    (
                        "轻影 M5 鼠标",
                        "轻影 M5 是轻量化无线鼠标，支持多档 DPI 和板载配置。标准零售价 299 元，适合办公及游戏场景。",
                    ),
                    (
                        "视界 27P 显示器",
                        "视界 27P 为 27 英寸 2K 165Hz 显示器，支持自适应同步和低蓝光模式。标准零售价 1699 元，适合设计、影音和高刷新率游戏。",
                    ),
                    (
                        "组合购买建议",
                        "移动办公建议选择星云 X1 与云声 Air 2；桌面办公建议选择极光 K87 与轻影 M5；需要高刷新率大屏时可搭配视界 27P。实际库存和成交价以商品页面为准。",
                    ),
                ],
            },
            {
                "filename": "交易配送与售后政策.md",
                "sections": [
                    (
                        "订单与支付",
                        "订单提交后需在 30 分钟内完成支付，超时可能自动关闭。支付成功后如需修改地址，应在进入仓库拣货前联系客服处理。",
                    ),
                    (
                        "发货与配送",
                        "现货订单通常在支付成功后 24 小时内发货。用户可在订单详情查看承运商、运单号、最新物流节点和预计送达时间；偏远地区时效可能延长。",
                    ),
                    (
                        "七天无理由退货",
                        "自商品签收之日起七日内，商品完好、配件和赠品齐全且不影响二次销售时，可申请七天无理由退货。定制商品、已激活数字商品及法律规定不适用的商品除外。",
                    ),
                    (
                        "质量问题换货",
                        "商品存在非人为性能故障时，用户应提交故障描述、照片或视频。审核通过后可按政策安排换货或维修；寄回前请备份数据并移除个人账号。",
                    ),
                    (
                        "保修范围",
                        "手机整机、耳机、键盘、鼠标和显示器均提供一年有限保修。人为跌落、进液、私自拆修、非官方改装和不可抗力造成的损坏不属于免费保修。",
                    ),
                    (
                        "退款时效",
                        "退货验收通过后，退款通常在 1 至 3 个工作日内原路发起。具体到账时间由银行或支付机构决定，退款进度可通过退款单或售后工单查询。",
                    ),
                    (
                        "电子发票",
                        "订单完成后可申请电子发票。企业抬头需要填写准确的企业名称和纳税人识别号，审核后发送到账号绑定邮箱。",
                    ),
                    (
                        "隐私与数据",
                        "送修手机前请备份并清除个人数据。客服不得索要用户密码、短信验证码或支付口令；涉及身份核验时只使用系统规定的最小必要信息。",
                    ),
                ],
            },
            {
                "filename": "常见设备故障排查指南.md",
                "sections": [
                    (
                        "云声 Air 2 耳机无声音",
                        "云声 Air 2 耳机无声音时，先检查手机和耳机音量，并确认系统声音输出设备已选择云声 Air 2。将双耳放回充电盒十秒后重新取出；仍无声时，在蓝牙设置中取消配对后重新连接，并确认左右耳均有电。完成上述步骤仍未恢复，可按说明书执行耳机重置，或提交售后报修。",
                    ),
                    (
                        "耳机单耳无声",
                        "单侧耳机无声时，先清洁充电触点并确认无声耳机能够正常充电，再将双耳同时放回充电盒重新配对。检查手机的左右声道平衡是否位于中间。若换一台设备连接后仍是同一侧无声，应记录序列号和故障现象并申请检测。",
                    ),
                    (
                        "耳机杂音或频繁断连",
                        "出现杂音或断连时，应先远离无线路由器等强干扰源，保持耳机与设备距离在十米以内，关闭并重新打开蓝牙，再删除配对记录后重连。可同时检查手机系统与耳机固件是否为最新版本；多台设备均能复现时再提交报修。",
                    ),
                    (
                        "手机无法开机或充电",
                        "手机无法开机时，使用原装或合规充电器连续充电三十分钟，再长按电源键尝试启动。无法充电时检查充电口是否有异物，并更换已确认正常的线材和适配器交叉验证。不得自行拆机；仍无反应时转售后检测。",
                    ),
                    (
                        "显示器黑屏或无信号",
                        "显示器黑屏或无信号时，确认电源指示灯、输入源和视频线接口，重新插拔线缆并选择与接口一致的输入源。可更换线缆或连接另一台设备交叉验证。若有背光但持续无画面，应记录接口和设备型号后申请检测。",
                    ),
                    (
                        "键盘鼠标连接失灵",
                        "键盘或鼠标失灵时，先确认电量和连接模式，重新插拔接收器或更换 USB 接口。蓝牙模式下删除配对后重新连接，有线模式下可连接另一台电脑交叉验证。只有部分按键失灵时，请记录具体按键并提交售后检测。",
                    ),
                    (
                        "售后处理边界",
                        "故障排查阶段不得直接承诺退款或换货。用户完成基础排查后问题仍存在，应收集商品型号、订单号、故障现象和已尝试步骤，创建报修工单；是否维修、换货或退款以检测结果和售后政策审核为准。",
                    ),
                ],
            },
        ],
    },
    {
        "name": "星云科技客服运营知识库",
        "description": "供客服团队使用的服务规范、工单分级、人工接管、投诉升级与信息安全手册",
        "documents": [
            {
                "filename": "客服服务规范.md",
                "sections": [
                    (
                        "服务原则",
                        "客服应做到准确、简洁、友善和可追踪。先确认用户诉求，再说明处理依据和下一步；不得编造订单、物流、库存或退款结果。",
                    ),
                    (
                        "身份与权限核验",
                        "查询订单、物流、退款和工单前必须使用当前登录用户身份执行权限校验。不得仅凭用户在消息中提供的用户编号访问其他账户数据。",
                    ),
                    (
                        "首响与跟进时效",
                        "在线人工客服目标首响时间为 2 分钟；普通工单应在 4 个工作小时内首次响应，高优先级工单应在 30 分钟内开始处理。无法按时完成时应主动告知预计时间。",
                    ),
                    (
                        "沟通结构",
                        "推荐使用确认诉求、说明结论、给出依据、列出下一步的四段式回复。需要用户补充材料时，应一次性列出所需信息，避免反复追问。",
                    ),
                    (
                        "禁止行为",
                        "禁止承诺系统无法保证的赔偿或到账时间，禁止泄露内部账号、密钥和其他用户信息，禁止要求用户提供密码、验证码或完整银行卡信息。",
                    ),
                    (
                        "会话结束",
                        "问题处理完成后，应总结处理结果和关联工单号，询问用户是否还有其他问题。人工服务结束时将会话交回智能客服，并保留完整消息记录。",
                    ),
                ],
            },
            {
                "filename": "工单分级与升级处理手册.md",
                "sections": [
                    (
                        "工单优先级",
                        "普通咨询设为 normal；影响订单履约或多次联系未解决可设为 high；涉及大面积服务不可用、资金安全或重大舆情时应立即升级并通知值班负责人。",
                    ),
                    (
                        "退款工单",
                        "退款申请必须关联订单号、退款原因和资格校验结果。创建前检查同一订单是否已有 pending、approved 或 processing 状态的申请，存在时返回原退款单，禁止重复创建。",
                    ),
                    (
                        "物流异常",
                        "超过预计送达时间、物流连续 48 小时无更新或显示异常签收时，应创建物流工单并记录承运商、运单号、最后节点和用户可联系时间。",
                    ),
                    (
                        "投诉升级",
                        "出现投诉、赔偿、律师、监管或媒体相关表述时，机器人应转人工。客服记录事实和用户诉求，不作未经授权的责任认定，并按权限升级主管。",
                    ),
                    (
                        "人工接管",
                        "客服从实时队列接管会话后，只有接管人或管理员可以回复。处理期间机器人暂停业务回答；结束接管后会话恢复机器人模式。",
                    ),
                    (
                        "信息安全事件",
                        "发现账号疑似被盗、异常支付、敏感数据泄露或提示词注入攻击时，应停止自动操作、保留审计记录并升级安全负责人，避免在聊天中暴露内部实现细节。",
                    ),
                    (
                        "关闭标准",
                        "只有在已给出明确处理结果、用户确认无需继续跟进，或按规定多次联系无响应时才能关闭工单。关闭时必须填写结果摘要。",
                    ),
                ],
            },
        ],
    },
]


def _ensure_demo_knowledge(db: Session) -> None:
    legacy = db.scalar(select(KnowledgeBase).where(KnowledgeBase.name == "企业客服知识库"))
    first_name = DEMO_KNOWLEDGE_BASES[0]["name"]
    if legacy and not db.scalar(select(KnowledgeBase).where(KnowledgeBase.name == first_name)):
        legacy.name = first_name
        legacy.description = DEMO_KNOWLEDGE_BASES[0]["description"]
        # SessionLocal disables autoflush. Persist the rename before looking up the
        # new name, otherwise the loop below would try to insert a duplicate base.
        db.flush()

    for base_spec in DEMO_KNOWLEDGE_BASES:
        knowledge_base = db.scalar(
            select(KnowledgeBase).where(KnowledgeBase.name == base_spec["name"])
        )
        if not knowledge_base:
            knowledge_base = KnowledgeBase(
                name=base_spec["name"], description=base_spec["description"]
            )
            db.add(knowledge_base)
            db.flush()
        if db.get(KnowledgeAccess, knowledge_base.id) is None:
            db.add(KnowledgeAccess(base_id=knowledge_base.id, visibility="public" if base_spec["name"] == "星云科技产品与售后知识库" else "internal"))
            db.flush()
        for document_spec in base_spec["documents"]:
            existing = db.scalar(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.knowledge_base_id == knowledge_base.id,
                    KnowledgeDocument.filename == document_spec["filename"],
                )
            )
            if existing:
                continue
            sections = document_spec["sections"]
            document = KnowledgeDocument(
                knowledge_base_id=knowledge_base.id,
                filename=document_spec["filename"],
                file_type="md",
                storage_path=f"seed://{knowledge_base.id}/{document_spec['filename']}",
                status="ready",
                chunk_count=len(sections),
            )
            db.add(document)
            db.flush()
            for index, (section, content) in enumerate(sections):
                db.add(
                    DocumentChunk(
                        document_id=document.id,
                        knowledge_base_id=knowledge_base.id,
                        chunk_index=index,
                        content=content,
                        section=section,
                        start_char=0,
                        end_char=len(content),
                    )
                )


def seed_demo(db: Session) -> None:
    if db.scalar(select(User.id).limit(1)):
        _ensure_demo_knowledge(db)
        db.commit()
        return

    customer = User(
        username="customer",
        email="customer@example.com",
        password_hash=hash_password("Customer123!"),
        role="customer",
    )
    service = User(
        username="service",
        email="service@example.com",
        password_hash=hash_password("Service123!"),
        role="service",
    )
    admin = User(
        username="admin",
        email="admin@example.com",
        password_hash=hash_password("Admin123!"),
        role="admin",
    )
    db.add_all([customer, service, admin])
    db.flush()

    products = [
        Product(
            sku="PHONE-X1",
            name="星云 X1 手机",
            category="手机",
            description="6.7 英寸屏幕，支持 5G 与无线充电",
            price=Decimal("3999.00"),
            stock=68,
            locked_stock=3,
        ),
        Product(
            sku="EAR-AIR2",
            name="云声 Air 2 耳机",
            category="耳机",
            description="主动降噪，续航 30 小时",
            price=Decimal("699.00"),
            stock=120,
            locked_stock=6,
        ),
        Product(
            sku="KEY-K87",
            name="极光 K87 机械键盘",
            category="键盘",
            description="87 键热插拔机械键盘",
            price=Decimal("459.00"),
            stock=45,
            locked_stock=2,
        ),
        Product(
            sku="MOUSE-M5",
            name="轻影 M5 鼠标",
            category="鼠标",
            description="轻量化无线游戏鼠标",
            price=Decimal("299.00"),
            stock=90,
            locked_stock=8,
        ),
        Product(
            sku="MON-27P",
            name="视界 27P 显示器",
            category="显示器",
            description="27 英寸 2K 165Hz 显示器",
            price=Decimal("1699.00"),
            stock=24,
            locked_stock=1,
        ),
    ]
    db.add_all(products)
    db.flush()

    order = Order(
        order_no="EM20260710001",
        user_id=customer.id,
        status="paid",
        payment_status="paid",
        shipping_status="shipped",
        total_amount=Decimal("4698.00"),
    )
    order.items = [
        OrderItem(
            product_id=products[0].id,
            product_name=products[0].name,
            quantity=1,
            unit_price=products[0].price,
        ),
        OrderItem(
            product_id=products[1].id,
            product_name=products[1].name,
            quantity=1,
            unit_price=products[1].price,
        ),
    ]
    order.logistics = Logistics(
        carrier="顺丰速运",
        tracking_no="SF202607100001",
        status="运输中",
        latest_event="包裹已到达上海分拨中心",
        estimated_delivery=date.today() + timedelta(days=2),
    )
    db.add(order)

    db.add(
        ServiceTicket(
            ticket_no="TKDEMO001",
            user_id=customer.id,
            order_no=order.order_no,
            category="logistics",
            title="物流进度咨询",
            description="物流两天没有更新",
            priority="normal",
            status="processing",
            assignee_id=service.id,
        )
    )
    db.add(Conversation(user_id=customer.id, title="欢迎使用 EnterpriseMind"))

    _ensure_demo_knowledge(db)
    db.commit()
