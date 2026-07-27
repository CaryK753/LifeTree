"""HTML email template helpers shared by all email-sending code.

Centralises the visual style so verification codes, risk warnings and
future email types all look consistent. Links inside emails use the
admin-configured "service address" so they resolve to the public URL
of this LifeTree instance (rather than an internal Docker hostname).
"""

from __future__ import annotations

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from app.llm.registry import get_service_address, get_smtp_config


def get_service_url() -> str:
    """Return the admin-configured service URL, with trailing slash stripped.

    Falls back to ``https://lifetree.example.com`` (placeholder) when unset,
    so emails always contain *some* clickable link — the admin should set
    the real address in /admin → Auth & Registration → Service address.
    """
    addr = (get_service_address() or "").strip()
    if addr:
        return addr.rstrip("/")
    return "https://lifetree.example.com"


def render_email_html(
    *,
    title: str,
    preheader: str = "",
    body_html: str,
) -> str:
    """Wrap ``body_html`` in the standard LifeTree email shell.

    ``title`` is shown in the header band and as the page <title>.
    ``preheader`` is the short preview text some email clients show in the
    inbox list (hidden in the body itself).
    """
    brand_url = get_service_url()
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="x-apple-disable-message-reformatting" />
  <title>{title}</title>
  <style>
    /* Reset — email clients need explicit resets */
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{ margin: 0; padding: 0; width: 100% !important; -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }}
    table {{ border-collapse: collapse; width: 100%; }}
    img {{ border: 0; max-width: 100%; height: auto; display: block; }}
    a {{ color: #2563eb; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}

    /* Layout */
    .body {{ background-color: #f4f5f7; padding: 24px 12px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; color: #1f2937; }}
    .container {{ max-width: 560px; margin: 0 auto; background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
    .header {{ background: linear-gradient(135deg, #1f7a5a 0%, #2da577 100%); padding: 24px 32px; }}
    .header .brand {{ font-size: 20px; font-weight: 600; color: #ffffff; letter-spacing: 0.02em; }}
    .header .subtitle {{ font-size: 13px; color: rgba(255,255,255,0.85); margin-top: 4px; }}
    .content {{ padding: 32px; }}
    .footer {{ padding: 20px 32px; background: #f9fafb; border-top: 1px solid #e5e7eb; font-size: 12px; color: #6b7280; text-align: center; }}
    .footer a {{ color: #6b7280; }}

    /* Content elements */
    h1 {{ font-size: 20px; font-weight: 600; color: #111827; margin: 0 0 16px; }}
    p {{ font-size: 14px; line-height: 1.6; color: #374151; margin: 0 0 14px; }}
    .code-box {{ background: #f0fdf4; border: 1px dashed #86efac; border-radius: 8px; padding: 20px; text-align: center; margin: 20px 0; }}
    .code {{ font-size: 32px; font-weight: 700; letter-spacing: 0.4em; color: #166534; font-family: 'SF Mono', Menlo, Consolas, monospace; }}
    .btn {{ display: inline-block; background: #2da577; color: #ffffff !important; font-size: 14px; font-weight: 600; padding: 12px 28px; border-radius: 8px; margin: 16px 0; }}
    .btn:hover {{ background: #1f7a5a; text-decoration: none; }}
    .alert {{ background: #fef3c7; border-left: 4px solid #f59e0b; padding: 12px 16px; border-radius: 4px; margin: 16px 0; font-size: 13px; color: #92400e; }}
    .meta {{ font-size: 12px; color: #9ca3af; margin-top: 24px; padding-top: 16px; border-top: 1px solid #f3f4f6; }}
    .preheader {{ display: none; max-height: 0; overflow: hidden; opacity: 0; }}
  </style>
</head>
<body>
  <div class="preheader">{preheader}</div>
  <div class="body">
    <div class="container">
      <div class="header">
        <div class="brand">LifeTree</div>
        <div class="subtitle">让每一个重大人生选择，都有迹可循</div>
      </div>
      <div class="content">
        {body_html}
      </div>
      <div class="footer">
        <p style="margin:0 0 6px;">LifeTree — 长期决策推演平台</p>
        <a href="{brand_url}">{brand_url}</a>
      </div>
    </div>
  </div>
</body>
</html>"""


def render_verification_code_email(code: str, expires_in_minutes: int = 10) -> tuple[str, str]:
    """Return (subject, html_body) for a verification-code email.

    The plain-text fallback is derived from the same data so users whose
    clients disable HTML still see the code.
    """
    service_url = get_service_url()
    body_html = f"""
<h1>验证码 / Verification Code</h1>
<p>你正在注册 LifeTree 账号，请使用以下验证码完成注册：</p>
<p>You are registering a LifeTree account. Please use the following code to complete registration:</p>
<div class="code-box">
  <span class="code">{code}</span>
</div>
<p style="text-align:center; font-size:13px; color:#6b7280;">验证码 {expires_in_minutes} 分钟内有效 · Valid for {expires_in_minutes} minutes</p>
<p>如果你没有请求此验证码，请忽略此邮件，无需任何操作。</p>
<p>If you didn't request this code, you can safely ignore this email.</p>
<div class="meta">
  <a href="{service_url}" class="btn">前往 LifeTree →</a><br />
  <span style="font-size:12px; color:#9ca3af;">{service_url}</span>
</div>"""
    subject = f"[LifeTree] 验证码 {code} · Verification code"
    html = render_email_html(
        title="LifeTree 验证码",
        preheader=f"Your LifeTree verification code is {code}",
        body_html=body_html,
    )
    return subject, html


def render_risk_warning_email(
    *,
    user_display_name: str,
    title: str,
    body_text: str,
    severity: str = "warning",
) -> tuple[str, str]:
    """Return (subject, html_body) for a risk-warning notification email.

    ``severity`` controls the colour of the alert band: ``critical`` → red,
    ``warning`` → amber, anything else → neutral.
    """
    service_url = get_service_url()
    severity_label = {
        "critical": "紧急 · Critical",
        "warning": "警告 · Warning",
        "info": "提示 · Info",
    }.get(severity, "通知 · Notice")

    # Escape basic HTML in body_text (it's plain text from the LLM/notif svc).
    safe_body = (
        body_text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br />")
    )

    body_html = f"""
<h1>{title}</h1>
<div class="alert">{severity_label}</div>
<p>你好 <strong>{user_display_name}</strong>，</p>
<p>LifeTree 监测到与你关注的目标相关的风险变化：</p>
<p>{safe_body}</p>
<div class="meta">
  <a href="{service_url}/notifications" class="btn">查看详情 →</a><br />
  <span style="font-size:12px; color:#9ca3af;">你收到这封邮件是因为你在 LifeTree 开启了邮件通知。</span><br />
  <span style="font-size:12px; color:#9ca3af;">You receive this email because email notifications are enabled in your LifeTree profile.</span>
</div>"""
    subject = f"[LifeTree] {title}"
    html = render_email_html(
        title=title,
        preheader=f"{severity_label}: {title}",
        body_html=body_html,
    )
    return subject, html


def build_html_message(
    *,
    to_addr: str,
    subject: str,
    html_body: str,
    plain_text_fallback: str,
) -> MIMEMultipart:
    """Build a MIMEMultipart message with both plain-text and HTML parts.

    Uses the admin-configured SMTP "from" / sender name. Callers handle
    the actual SMTP connection.
    """
    smtp = get_smtp_config()
    from_addr = smtp["from"] or "notify@lifetree.local"
    sender_name = smtp.get("sender_name", "LifeTree") or "LifeTree"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((sender_name, from_addr))
    msg["To"] = to_addr
    msg.attach(MIMEText(plain_text_fallback, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    return msg


__all__ = [
    "build_html_message",
    "get_service_url",
    "render_email_html",
    "render_risk_warning_email",
    "render_verification_code_email",
]
