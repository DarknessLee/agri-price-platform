"""邮件通道（契约 M3 §3）：基于 smtplib 发送，本地 Mailpit 收信。

设计原则与缓存层一致——邮件是"锦上添花"的能力，任何发送失败都必须降级为
``sent=false`` 并写 ``sys_email_log`` 失败原因，绝不把异常抛给业务调用方。
- ``MAIL_ENABLED=false`` 时不建立连接，直接返回关闭原因；
- 连接与读写超时统一用 ``MAIL_TIMEOUT``，避免 SMTP 卡住业务请求；
- 每次发送（成功/失败/关闭）都落一条 ``sys_email_log``，供监控页与排障使用。
"""
from __future__ import annotations

import smtplib
from datetime import datetime
from email.message import EmailMessage
from email.utils import formatdate

from sqlalchemy import func, select

from ..config import MAIL_ENABLED, MAIL_FROM, MAIL_HOST, MAIL_PORT, MAIL_TIMEOUT, MAIL_TO
from ..database import SessionLocal
from ..models import EmailLog

STATUS_SENT = "已发送"
STATUS_FAILED = "失败"


def alert_levels() -> set[str]:
    """需要邮件外发的预警等级集合（默认仅"高"）。"""
    from ..config import MAIL_ALERT_LEVELS

    return {item.strip() for item in str(MAIL_ALERT_LEVELS or "").split(",") if item.strip()}


def health() -> dict:
    """邮件通道配置态（不做 SMTP 探测，避免监控页每次刷新都触发连接）。"""
    return {
        "enabled": bool(MAIL_ENABLED),
        "endpoint": f"{MAIL_HOST}:{MAIL_PORT}",
        "web_ui": "http://127.0.0.1:8025" if MAIL_ENABLED else "",
    }


def _write_log(to_addr: str, subject: str, category: str, status: str, reason: str) -> None:
    """写发送记录；日志表写入失败只告警，不影响调用方。"""
    try:
        db = SessionLocal()
        try:
            db.add(
                EmailLog(
                    to_addr=str(to_addr or "")[:128],
                    subject=str(subject or "")[:200],
                    category=str(category or "系统")[:32],
                    status=str(status or STATUS_FAILED)[:8],
                    reason=str(reason or "")[:255],
                    created_at=datetime.now().replace(microsecond=0),
                )
            )
            db.commit()
        finally:
            db.close()
    except Exception:  # pragma: no cover - 邮件记录失败不影响业务
        pass


def send_mail(to: str | None = None, subject: str = "", body: str = "", category: str = "系统") -> dict:
    """发送一封纯文本邮件，返回 ``{sent,to,subject,status,reason}``；任何异常都不外抛。"""
    to_addr = str(to or MAIL_TO or "").strip()
    subject = str(subject or "").strip()[:200] or "农产品价格预测分析系统通知"
    body = str(body or "")[:8000]
    result = {"sent": False, "to": to_addr, "subject": subject, "status": STATUS_FAILED, "reason": ""}

    if not MAIL_ENABLED:
        result["reason"] = "邮件通道已关闭（MAIL_ENABLED=false）"
        _write_log(to_addr, subject, category, STATUS_FAILED, result["reason"])
        return result
    if not to_addr:
        result["reason"] = "缺少收件人地址（MAIL_TO 为空）"
        _write_log(to_addr, subject, category, STATUS_FAILED, result["reason"])
        return result

    try:
        message = EmailMessage()
        message["From"] = MAIL_FROM
        message["To"] = to_addr
        message["Subject"] = subject
        message["Date"] = formatdate(localtime=True)
        message.set_content(body or subject)
        with smtplib.SMTP(MAIL_HOST, MAIL_PORT, timeout=MAIL_TIMEOUT) as client:
            client.send_message(message)
        result.update(sent=True, status=STATUS_SENT, reason="")
    except Exception as exc:  # 连接/超时/协议错误统一降级
        result["reason"] = f"{type(exc).__name__}: {exc}"[:255]
    _write_log(to_addr, subject, category, result["status"], result["reason"])
    return result


def test(to: str | None = None) -> dict:
    """发送连通性测试邮件，返回契约 §3 要求的 ``{sent,to,subject,status,note}``。"""
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subject = f"邮件通道连通性测试（{stamp}）"
    body = (
        "这是一封来自农产品价格预测分析系统的连通性测试邮件。\n"
        f"发送时间：{stamp}\n"
        f"SMTP 通道：{MAIL_HOST}:{MAIL_PORT}\n"
        "收到本邮件说明邮件通道配置正常。"
    )
    outcome = send_mail(to=to, subject=subject, body=body, category="系统")
    note = outcome.get("reason") or "邮件已提交 SMTP 服务器，可在 Mailpit Web（http://127.0.0.1:8025）查看"
    return {
        "sent": outcome["sent"],
        "to": outcome["to"],
        "subject": outcome["subject"],
        "status": outcome["status"],
        "note": str(note)[:255],
    }


def logs(limit: int = 20, status: str | None = None) -> dict:
    """最近发送记录分页（不分页，直接取最近 limit 条），含成功/失败计数。"""
    limit = max(1, min(int(limit or 20), 200))
    status = (status or "").strip()
    db = SessionLocal()
    try:
        conditions = [EmailLog.status == status] if status else []
        total = int(db.execute(select(func.count(EmailLog.id)).where(*conditions)).scalar() or 0)
        rows = (
            db.execute(
                select(EmailLog)
                .where(*conditions)
                .order_by(EmailLog.created_at.desc(), EmailLog.id.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
        sent = int(
            db.execute(select(func.count(EmailLog.id)).where(EmailLog.status == STATUS_SENT)).scalar() or 0
        )
        failed = int(
            db.execute(select(func.count(EmailLog.id)).where(EmailLog.status == STATUS_FAILED)).scalar() or 0
        )
        items = [
            {
                "id": int(row.id),
                "to_addr": row.to_addr or "",
                "subject": row.subject or "",
                "category": row.category or "系统",
                "status": row.status or "",
                "reason": row.reason or "",
                "created_at": row.created_at.strftime("%Y-%m-%dT%H:%M:%S") if row.created_at else "",
            }
            for row in rows
        ]
        return {"list": items, "total": total, "sent": sent, "failed": failed}
    finally:
        db.close()
