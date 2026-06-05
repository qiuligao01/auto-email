import os
import requests
import json
import smtplib
import traceback
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header
from datetime import datetime


WEATHER_CODE_MAP = {
    0: "晴",
    1: "大致晴朗",
    2: "局部多云",
    3: "阴",
    45: "雾",
    48: "雾凇",
    51: "小毛毛雨",
    53: "中等毛毛雨",
    55: "大毛毛雨",
    56: "冻毛毛雨",
    57: "强冻毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨",
    67: "强冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "雪粒",
    80: "小阵雨",
    81: "中等阵雨",
    82: "强阵雨",
    85: "小阵雪",
    86: "强阵雪",
    95: "雷暴",
    96: "雷暴伴小冰雹",
    99: "雷暴伴强冰雹"
}


def weather_desc(code):
    """天气代码转中文描述"""
    return WEATHER_CODE_MAP.get(code, f"未知天气代码 {code}")


def load_email_config():
    """加载并验证邮件配置"""
    config_json = os.getenv("EMAIL_CONFIG")
    if not config_json:
        raise ValueError("环境变量 'EMAIL_CONFIG' 未设置或为空，请检查环境变量配置。")

    try:
        config = json.loads(config_json)
    except json.JSONDecodeError as e:
        raise ValueError(f"解析 'EMAIL_CONFIG' 时出错: {str(e)}")

    required_fields = [
        "smtp_server",
        "smtp_port",
        "smtp_user",
        "smtp_pass",
        "from_email",
        "to_emails",
        "subject",
        "body"
    ]

    for field in required_fields:
        if field not in config:
            raise ValueError(f"配置中缺少必需字段: {field}")

    to_emails = config["to_emails"]

    if isinstance(to_emails, str):
        config["to_emails"] = [email.strip() for email in to_emails.split(",") if email.strip()]
    elif not isinstance(to_emails, list):
        raise ValueError("配置中的 'to_emails' 应为一个邮件地址列表或逗号分隔的字符串")

    if not config["to_emails"]:
        raise ValueError("收件人列表为空，请检查 'to_emails' 配置。")

    return config


def load_telegram_config():
    """加载并验证 Telegram 配置"""
    tg_id = os.getenv("TG_ID")
    tg_token = os.getenv("TG_TOKEN")

    if tg_id and not tg_id.isdigit():
        raise ValueError("变量配置中的 'TG_ID' 应为数字，请检查配置。")

    if tg_token and ":" not in tg_token:
        raise ValueError("变量配置中的 'TG_TOKEN' 应该包含 ':'，请检查配置。")

    return tg_id, tg_token


def get_weather_html(weather_config):
    """获取天气信息并生成 HTML 邮件内容"""
    if not weather_config or not weather_config.get("enabled"):
        return ""

    city = weather_config.get("city", "当前城市")
    latitude = weather_config.get("latitude")
    longitude = weather_config.get("longitude")
    timezone = weather_config.get("timezone", "Asia/Shanghai")
    forecast_days = int(weather_config.get("forecast_days", 3))

    if latitude is None or longitude is None:
        return """
        <hr>
        <h2>天气信息配置错误</h2>
        <p>缺少 latitude 或 longitude，已跳过天气信息。</p>
        """

    url = "https://api.open-meteo.com/v1/forecast"

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "timezone": timezone,
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,relative_humidity_2m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max",
        "forecast_days": forecast_days
    }

    try:
        response = requests.get(url, params=params, timeout=20)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        return f"""
        <hr>
        <h2>天气信息获取失败</h2>
        <p>原因：{str(e)}</p>
        """

    current = data.get("current", {})
    daily = data.get("daily", {})

    current_code = current.get("weather_code")
    current_temp = current.get("temperature_2m")
    apparent_temp = current.get("apparent_temperature")
    humidity = current.get("relative_humidity_2m")
    wind_speed = current.get("wind_speed_10m")

    html = f"""
    <hr>
    <h2>{city}每日天气提醒</h2>

    <p>
        <strong>当前天气：</strong>{weather_desc(current_code)}<br>
        <strong>当前温度：</strong>{current_temp}℃<br>
        <strong>体感温度：</strong>{apparent_temp}℃<br>
        <strong>相对湿度：</strong>{humidity}%<br>
        <strong>当前风速：</strong>{wind_speed} km/h
    </p>

    <h3>未来 {forecast_days} 天天气</h3>

    <table border="1" cellpadding="6" cellspacing="0">
        <tr>
            <th>日期</th>
            <th>天气</th>
            <th>最低温</th>
            <th>最高温</th>
            <th>降水概率</th>
            <th>最大风速</th>
        </tr>
    """

    times = daily.get("time", [])
    codes = daily.get("weather_code", [])
    temp_max = daily.get("temperature_2m_max", [])
    temp_min = daily.get("temperature_2m_min", [])
    rain_prob = daily.get("precipitation_probability_max", [])
    wind_max = daily.get("wind_speed_10m_max", [])

    for i in range(len(times)):
        html += f"""
        <tr>
            <td>{times[i]}</td>
            <td>{weather_desc(codes[i])}</td>
            <td>{temp_min[i]}℃</td>
            <td>{temp_max[i]}℃</td>
            <td>{rain_prob[i]}%</td>
            <td>{wind_max[i]} km/h</td>
        </tr>
        """

    html += "</table>"

    if rain_prob and rain_prob[0] is not None and rain_prob[0] >= 50:
        html += """
        <p>
            <strong>提醒：</strong>今天降水概率较高，出门建议带伞。
        </p>
        """

    return html


def send_email(smtp_server, smtp_port, smtp_user, smtp_pass, from_email, to_email, subject, body):
    """发送邮件"""
    smtp_port = int(smtp_port)

    if smtp_port not in [465, 587]:
        raise ValueError(f"不支持的 SMTP 端口号: {smtp_port}，仅支持 465 或 587，请检查配置。")

    msg = MIMEMultipart()
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = Header(subject, "utf-8")
    msg.attach(MIMEText(body, "html", "utf-8"))

    try:
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=30) as server:
                server.login(smtp_user, smtp_pass)
                server.sendmail(from_email, to_email, msg.as_string())

        elif smtp_port == 587:
            with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(smtp_user, smtp_pass)
                server.sendmail(from_email, to_email, msg.as_string())

        print(f"邮件已成功发送到 {to_email}")
        return True

    except Exception as e:
        error_message = str(e)

        if smtp_user:
            error_message = error_message.replace(smtp_user, "[SMTP 账号]")
        if smtp_pass:
            error_message = error_message.replace(smtp_pass, "[SMTP 密码]")

        print(f"发送邮件到 {to_email} 失败: {error_message}")
        traceback.print_exc()
        return False


def send_telegram_notification(tg_id, tg_token, success_emails, failed_emails_with_reasons):
    """发送 Telegram 消息"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    success_count = len(success_emails)
    failure_count = len(failed_emails_with_reasons)
    total_count = success_count + failure_count

    message = (
        "🤖 邮件群发状态报告\n"
        f"⏰ 时间: {now}\n"
        f"📊 总计: {total_count} 个邮箱\n"
        f"✅ 成功: {success_count} 个 | ❌ 失败: {failure_count} 个\n\n"
    )

    for email in success_emails:
        message += f"邮箱：{email}\n状态: ✅ 发送成功\n\n"

    for email, reason in failed_emails_with_reasons.items():
        message += f"邮箱：{email}\n状态: ❌ 发送失败\n失败原因: {reason}\n\n"

    url = f"https://api.telegram.org/bot{tg_token}/sendMessage"

    payload = {
        "chat_id": tg_id,
        "text": message
    }

    try:
        response = requests.post(url, json=payload, timeout=20)

        if response.status_code == 200:
            print("Telegram 通知发送成功")
        else:
            print(f"Telegram 通知发送失败: {response.status_code}, {response.text}")

    except Exception as e:
        print(f"发送 Telegram 通知时出现异常: {str(e)}")
        traceback.print_exc()


if __name__ == "__main__":
    try:
        config = load_email_config()

        smtp_server = config["smtp_server"]
        smtp_port = int(config["smtp_port"])
        smtp_user = config["smtp_user"]
        smtp_pass = config["smtp_pass"]
        from_email = config["from_email"]
        to_emails = config["to_emails"]
        subject = config["subject"]

        body = config["body"]

        # 在邮件正文后面追加天气信息
        body += get_weather_html(config.get("weather"))

        tg_id, tg_token = load_telegram_config()
        send_telegram = bool(tg_id and tg_token)

        success_emails = []
        failed_emails_with_reasons = {}

        for email in to_emails:
            try:
                result = send_email(
                    smtp_server,
                    smtp_port,
                    smtp_user,
                    smtp_pass,
                    from_email,
                    email,
                    subject,
                    body
                )

                if result:
                    success_emails.append(email)
                else:
                    failed_emails_with_reasons[email] = "未知错误"

            except Exception as e:
                failed_emails_with_reasons[email] = str(e)

        if send_telegram:
            send_telegram_notification(
                tg_id,
                tg_token,
                success_emails,
                failed_emails_with_reasons
            )
        else:
            print("Telegram 通知配置缺失，跳过发送 Telegram 通知。")

    except Exception as e:
        print(f"脚本运行时发生异常: {str(e)}")
        traceback.print_exc()
