"""Declarative field registry for messaging-platform configuration.

Single source of truth for what each gateway platform needs to be
configured from a UI (the web Messaging page, ``/api/messaging``).

Every field maps 1:1 to an environment variable persisted in
``{SPARK_HOME}/.env`` — the same storage the gateway actually reads
(see ``gateway/config.py::_apply_env_overrides`` and the per-platform
adapters under ``gateway/platforms/``).  The interactive CLI wizard
(``spark gateway setup`` in ``spark_cli/gateway.py::_PLATFORMS``) writes
the same variables.

Enablement convention:

- ``whatsapp`` / ``webhook`` / ``api_server`` have real ``*_ENABLED``
  env flags that the gateway reads directly.
- Credential-based platforms (telegram, discord, ...) are auto-enabled
  by the gateway whenever their credentials are present.  For these the
  ``enabled_env`` flag is advisory: the API persists it so the UI can
  remember an explicit off-toggle, and treats "unset" as
  "enabled if configured".
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldSpec:
    """One configurable value, backed by an environment variable."""

    key: str  # env var name (persisted to {SPARK_HOME}/.env)
    label: str
    description: str = ""
    type: str = "text"  # "text" | "secret" | "bool" | "number"
    placeholder: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "type": self.type,
            "placeholder": self.placeholder,
        }


@dataclass(frozen=True)
class PlatformSpec:
    """Declarative configuration spec for one messaging platform."""

    id: str
    name: str
    description: str
    help_text: str  # "Get your credentials" copy
    setup_guide_url: str
    enabled_env: str  # env flag recording the on/off toggle
    required: tuple[FieldSpec, ...] = ()
    recommended: tuple[FieldSpec, ...] = ()
    advanced: tuple[FieldSpec, ...] = ()
    # True when the gateway itself reads enabled_env (vs advisory-only).
    enabled_env_is_native: bool = False

    def all_fields(self) -> tuple[FieldSpec, ...]:
        return self.required + self.recommended + self.advanced


def _allowlist(key: str, what: str = "user IDs") -> FieldSpec:
    return FieldSpec(
        key=key,
        label=f"Allowed {what}",
        description=(
            f"Comma-separated {what} allowed to talk to the bot. "
            "Without this, unknown users are denied by default (DM pairing can grant access)."
        ),
        placeholder="id1,id2",
    )


def _home_channel(key: str, what: str = "channel ID") -> FieldSpec:
    return FieldSpec(
        key=key,
        label=f"Home {what}",
        description=f"Default {what} for cron results and notifications (set later with /set-home).",
    )


_SPECS: tuple[PlatformSpec, ...] = (
    PlatformSpec(
        id="telegram",
        name="Telegram",
        description="Chat with Spark from Telegram DMs, groups, and topics.",
        help_text=(
            "In Telegram, talk to @BotFather, run /newbot, and copy the token it gives you. "
            "Then grab your numeric user ID from @userinfobot."
        ),
        setup_guide_url="https://core.telegram.org/bots/features#creating-a-new-bot",
        enabled_env="TELEGRAM_ENABLED",
        required=(
            FieldSpec(
                key="TELEGRAM_BOT_TOKEN",
                label="Bot token",
                description="Create a bot with @BotFather, then paste the token it gives you.",
                type="secret",
                placeholder="123456789:ABC...",
            ),
        ),
        recommended=(
            _allowlist("TELEGRAM_ALLOWED_USERS", "Telegram user IDs"),
            _home_channel("TELEGRAM_HOME_CHANNEL", "chat ID"),
        ),
        advanced=(
            FieldSpec(
                key="TELEGRAM_REQUIRE_MENTION",
                label="Require @mention in groups",
                description="Only respond in group chats when the bot is mentioned.",
                type="bool",
            ),
            FieldSpec(
                key="TELEGRAM_REPLY_TO_MODE",
                label="Reply threading mode",
                description="off, first, or all — how replies thread to your message.",
                placeholder="first",
            ),
            FieldSpec(
                key="TELEGRAM_REACTIONS",
                label="Emoji reactions",
                description="Let the bot react to messages with emoji.",
                type="bool",
            ),
        ),
    ),
    PlatformSpec(
        id="discord",
        name="Discord",
        description="Run Spark as a Discord bot in servers, threads, and DMs.",
        help_text=(
            "Create an application at the Discord Developer Portal, add a Bot, enable the "
            "Message Content intent, and invite it with the bot + applications.commands scopes."
        ),
        setup_guide_url="https://discord.com/developers/applications",
        enabled_env="DISCORD_ENABLED",
        required=(
            FieldSpec(
                key="DISCORD_BOT_TOKEN",
                label="Bot token",
                description="Developer Portal → your app → Bot → Reset Token.",
                type="secret",
            ),
        ),
        recommended=(
            _allowlist("DISCORD_ALLOWED_USERS", "Discord user IDs"),
            _home_channel("DISCORD_HOME_CHANNEL"),
        ),
        advanced=(
            FieldSpec(
                key="DISCORD_REQUIRE_MENTION",
                label="Require @mention in channels",
                description="Only respond in channels when the bot is mentioned.",
                type="bool",
            ),
            FieldSpec(
                key="DISCORD_AUTO_THREAD",
                label="Auto-create threads",
                description="Answer channel messages in a new thread.",
                type="bool",
            ),
            FieldSpec(
                key="DISCORD_ALLOWED_CHANNELS",
                label="Allowed channel IDs",
                description="If set, the bot only responds in these channels.",
                placeholder="id1,id2",
            ),
            FieldSpec(
                key="DISCORD_IGNORED_CHANNELS",
                label="Ignored channel IDs",
                description="Channels where the bot never responds, even when mentioned.",
                placeholder="id1,id2",
            ),
        ),
    ),
    PlatformSpec(
        id="slack",
        name="Slack",
        description="Bring Spark into Slack channels and DMs via Socket Mode.",
        help_text=(
            "Create a Slack app, enable Socket Mode (copy the xapp- app token), add bot scopes "
            "like chat:write and the message events, then install it to copy the xoxb- bot token."
        ),
        setup_guide_url="https://api.slack.com/apps",
        enabled_env="SLACK_ENABLED",
        required=(
            FieldSpec(
                key="SLACK_BOT_TOKEN",
                label="Bot token (xoxb-…)",
                description="Settings → Install App → Bot User OAuth Token.",
                type="secret",
                placeholder="xoxb-...",
            ),
            FieldSpec(
                key="SLACK_APP_TOKEN",
                label="App token (xapp-…)",
                description="Settings → Socket Mode → App-Level Token with connections:write.",
                type="secret",
                placeholder="xapp-...",
            ),
        ),
        recommended=(
            _allowlist("SLACK_ALLOWED_USERS", "Slack member IDs"),
            _home_channel("SLACK_HOME_CHANNEL"),
        ),
        advanced=(
            FieldSpec(
                key="SLACK_REQUIRE_MENTION",
                label="Require @mention in channels",
                description="Only respond in channels when the bot is mentioned.",
                type="bool",
            ),
            FieldSpec(
                key="SLACK_ALLOW_BOTS",
                label="Allow messages from bots",
                description="Process messages sent by other bot users.",
                type="bool",
            ),
        ),
    ),
    PlatformSpec(
        id="mattermost",
        name="Mattermost",
        description="Connect Spark to a self-hosted Mattermost server.",
        help_text=(
            "In Mattermost go to Integrations → Bot Accounts → Add Bot Account, "
            "then copy the bot token and your server URL."
        ),
        setup_guide_url="https://developers.mattermost.com/integrate/reference/bot-accounts/",
        enabled_env="MATTERMOST_ENABLED",
        required=(
            FieldSpec(
                key="MATTERMOST_URL",
                label="Server URL",
                description="Your Mattermost server URL.",
                placeholder="https://mm.example.com",
            ),
            FieldSpec(
                key="MATTERMOST_TOKEN",
                label="Bot token",
                description="Token from the bot account you created.",
                type="secret",
            ),
        ),
        recommended=(
            _allowlist("MATTERMOST_ALLOWED_USERS", "Mattermost user IDs"),
            _home_channel("MATTERMOST_HOME_CHANNEL"),
        ),
        advanced=(
            FieldSpec(
                key="MATTERMOST_REPLY_MODE",
                label="Reply mode",
                description="off = flat channel messages, thread = replies nest under your message.",
                placeholder="off",
            ),
        ),
    ),
    PlatformSpec(
        id="matrix",
        name="Matrix",
        description="Talk to Spark from any Matrix homeserver, with optional E2EE.",
        help_text=(
            "Create a bot user on your homeserver and copy an access token "
            "(Element → Settings → Help & About → Access Token), or provide a user ID + password."
        ),
        setup_guide_url="https://matrix.org/docs/chat_basics/matrix-for-im/",
        enabled_env="MATRIX_ENABLED",
        required=(
            FieldSpec(
                key="MATRIX_HOMESERVER",
                label="Homeserver URL",
                description="Any Synapse/Conduit/Dendrite instance, or https://matrix.org.",
                placeholder="https://matrix.example.org",
            ),
            FieldSpec(
                key="MATRIX_ACCESS_TOKEN",
                label="Access token",
                description="Bot access token (leave empty to use user ID + password below).",
                type="secret",
            ),
        ),
        recommended=(
            _allowlist("MATRIX_ALLOWED_USERS", "Matrix user IDs"),
            _home_channel("MATRIX_HOME_ROOM", "room ID"),
        ),
        advanced=(
            FieldSpec(
                key="MATRIX_USER_ID",
                label="User ID",
                description="Full Matrix user ID — required for password login.",
                placeholder="@spark:matrix.example.org",
            ),
            FieldSpec(
                key="MATRIX_PASSWORD",
                label="Password",
                description="Used instead of an access token when provided.",
                type="secret",
            ),
            FieldSpec(
                key="MATRIX_ENCRYPTION",
                label="End-to-end encryption",
                description="Requires: pip install 'mautrix[encryption]'.",
                type="bool",
            ),
            FieldSpec(
                key="MATRIX_DEVICE_ID",
                label="Device ID",
                description="Stable device ID for E2EE sessions.",
            ),
        ),
    ),
    PlatformSpec(
        id="whatsapp",
        name="WhatsApp",
        description="Pair Spark with WhatsApp through a local bridge (QR-code login).",
        help_text=(
            "Enable WhatsApp here, then run `spark whatsapp` in a terminal to install "
            "the bridge and pair by scanning a QR code with your phone."
        ),
        setup_guide_url="https://faq.whatsapp.com/1317564962315842",
        enabled_env="WHATSAPP_ENABLED",
        enabled_env_is_native=True,
        recommended=(
            _allowlist("WHATSAPP_ALLOWED_USERS", "phone numbers"),
        ),
        advanced=(
            FieldSpec(
                key="WHATSAPP_MODE",
                label="Mode",
                description="bot = separate bot number, self-chat = message yourself.",
                placeholder="bot",
            ),
            FieldSpec(
                key="WHATSAPP_REQUIRE_MENTION",
                label="Require mention in groups",
                description="Only respond in group chats when mentioned.",
                type="bool",
            ),
        ),
    ),
    PlatformSpec(
        id="signal",
        name="Signal",
        description="Message Spark over Signal via a signal-cli REST API container.",
        help_text=(
            "Run the signal-cli-rest-api service (Docker) and link it to your Signal "
            "account, then point Spark at its HTTP URL and account number."
        ),
        setup_guide_url="https://github.com/bbernhard/signal-cli-rest-api",
        enabled_env="SIGNAL_ENABLED",
        required=(
            FieldSpec(
                key="SIGNAL_HTTP_URL",
                label="signal-cli REST URL",
                description="Base URL of your signal-cli-rest-api instance.",
                placeholder="http://127.0.0.1:8080",
            ),
            FieldSpec(
                key="SIGNAL_ACCOUNT",
                label="Account number",
                description="The Signal account (E.164 phone number) linked to the API.",
                placeholder="+15551234567",
            ),
        ),
        recommended=(
            _allowlist("SIGNAL_ALLOWED_USERS", "phone numbers"),
            _home_channel("SIGNAL_HOME_CHANNEL", "recipient"),
        ),
        advanced=(
            FieldSpec(
                key="SIGNAL_IGNORE_STORIES",
                label="Ignore stories",
                description="Skip processing Signal story posts.",
                type="bool",
            ),
        ),
    ),
    PlatformSpec(
        id="bluebubbles",
        name="BlueBubbles (iMessage)",
        description="Use iMessage with Spark through a BlueBubbles server on a Mac.",
        help_text=(
            "Install BlueBubbles on a Mac signed into iMessage, then copy the "
            "Server URL and password from BlueBubbles Settings → API."
        ),
        setup_guide_url="https://bluebubbles.app/",
        enabled_env="BLUEBUBBLES_ENABLED",
        required=(
            FieldSpec(
                key="BLUEBUBBLES_SERVER_URL",
                label="Server URL",
                description="Shown in BlueBubbles Settings → API.",
                placeholder="http://192.168.1.10:1234",
            ),
            FieldSpec(
                key="BLUEBUBBLES_PASSWORD",
                label="Server password",
                description="Shown in BlueBubbles Settings → API.",
                type="secret",
            ),
        ),
        recommended=(
            _allowlist("BLUEBUBBLES_ALLOWED_USERS", "phone numbers / iMessage IDs"),
            _home_channel("BLUEBUBBLES_HOME_CHANNEL", "recipient"),
        ),
        advanced=(
            FieldSpec(
                key="BLUEBUBBLES_WEBHOOK_HOST",
                label="Webhook host",
                description="Local interface for receiving BlueBubbles webhooks.",
                placeholder="127.0.0.1",
            ),
            FieldSpec(
                key="BLUEBUBBLES_WEBHOOK_PORT",
                label="Webhook port",
                description="Local port for receiving BlueBubbles webhooks.",
                type="number",
                placeholder="8645",
            ),
            FieldSpec(
                key="BLUEBUBBLES_SEND_READ_RECEIPTS",
                label="Send read receipts",
                description="Mark conversations as read after responding.",
                type="bool",
            ),
        ),
    ),
    PlatformSpec(
        id="homeassistant",
        name="Home Assistant",
        description="Expose Spark as a conversation agent for Home Assistant.",
        help_text=(
            "In Home Assistant, open your profile → Security and create a "
            "Long-Lived Access Token, then paste it with your instance URL."
        ),
        setup_guide_url="https://www.home-assistant.io/docs/authentication/",
        enabled_env="HOMEASSISTANT_ENABLED",
        required=(
            FieldSpec(
                key="HASS_TOKEN",
                label="Long-lived access token",
                description="Created from your Home Assistant profile → Security.",
                type="secret",
            ),
            FieldSpec(
                key="HASS_URL",
                label="Home Assistant URL",
                description="Base URL of your Home Assistant instance.",
                placeholder="http://homeassistant.local:8123",
            ),
        ),
    ),
    PlatformSpec(
        id="email",
        name="Email",
        description="Let Spark read and answer email over IMAP/SMTP.",
        help_text=(
            "Use a dedicated mailbox for Spark. For Gmail, enable 2FA and create an "
            "App Password; IMAP must be enabled on the account."
        ),
        setup_guide_url="https://support.google.com/accounts/answer/185833",
        enabled_env="EMAIL_ENABLED",
        required=(
            FieldSpec(
                key="EMAIL_ADDRESS",
                label="Email address",
                description="The address Spark will send and receive from.",
                placeholder="spark@example.com",
            ),
            FieldSpec(
                key="EMAIL_PASSWORD",
                label="Password / app password",
                description="For Gmail, use an App Password (not your regular password).",
                type="secret",
            ),
            FieldSpec(
                key="EMAIL_IMAP_HOST",
                label="IMAP host",
                description="Incoming-mail server.",
                placeholder="imap.gmail.com",
            ),
            FieldSpec(
                key="EMAIL_SMTP_HOST",
                label="SMTP host",
                description="Outgoing-mail server.",
                placeholder="smtp.gmail.com",
            ),
        ),
        recommended=(
            _allowlist("EMAIL_ALLOWED_USERS", "sender addresses"),
            _home_channel("EMAIL_HOME_ADDRESS", "address"),
        ),
    ),
    PlatformSpec(
        id="sms",
        name="SMS (Twilio)",
        description="Text with Spark over SMS using a Twilio phone number.",
        help_text=(
            "Copy your Account SID and Auth Token from the Twilio Console dashboard "
            "and configure a phone number with an inbound-SMS webhook."
        ),
        setup_guide_url="https://console.twilio.com/",
        enabled_env="SMS_ENABLED",
        required=(
            FieldSpec(
                key="TWILIO_ACCOUNT_SID",
                label="Account SID",
                description="Found on the Twilio Console dashboard.",
                placeholder="AC...",
            ),
            FieldSpec(
                key="TWILIO_AUTH_TOKEN",
                label="Auth token",
                description="Found on the Twilio Console dashboard.",
                type="secret",
            ),
            FieldSpec(
                key="TWILIO_PHONE_NUMBER",
                label="Twilio phone number",
                description="Number to send SMS from (E.164 format).",
                placeholder="+15551234567",
            ),
        ),
        recommended=(
            _allowlist("SMS_ALLOWED_USERS", "phone numbers"),
            _home_channel("SMS_HOME_CHANNEL", "phone number"),
        ),
    ),
    PlatformSpec(
        id="dingtalk",
        name="DingTalk",
        description="Connect Spark to DingTalk group chats via Stream Mode.",
        help_text=(
            "Create an application at open-dev.dingtalk.com, copy the AppKey (Client ID) "
            "and AppSecret, and enable Stream Mode on the bot."
        ),
        setup_guide_url="https://open-dev.dingtalk.com",
        enabled_env="DINGTALK_ENABLED",
        required=(
            FieldSpec(
                key="DINGTALK_CLIENT_ID",
                label="AppKey (Client ID)",
                description="From your DingTalk application credentials.",
            ),
            FieldSpec(
                key="DINGTALK_CLIENT_SECRET",
                label="AppSecret (Client Secret)",
                description="From your DingTalk application credentials.",
                type="secret",
            ),
        ),
        recommended=(
            _allowlist("DINGTALK_ALLOWED_USERS"),
        ),
    ),
    PlatformSpec(
        id="feishu",
        name="Feishu / Lark",
        description="Chat with Spark in Feishu or Lark via a bot app.",
        help_text=(
            "Create an app at open.feishu.cn (or open.larksuite.com for Lark), enable "
            "the Bot capability, and copy the App ID and App Secret."
        ),
        setup_guide_url="https://open.feishu.cn/",
        enabled_env="FEISHU_ENABLED",
        required=(
            FieldSpec(
                key="FEISHU_APP_ID",
                label="App ID",
                description="From your Feishu/Lark application.",
            ),
            FieldSpec(
                key="FEISHU_APP_SECRET",
                label="App secret",
                description="From your Feishu/Lark application.",
                type="secret",
            ),
        ),
        recommended=(
            _allowlist("FEISHU_ALLOWED_USERS"),
            _home_channel("FEISHU_HOME_CHANNEL", "chat ID"),
        ),
        advanced=(
            FieldSpec(
                key="FEISHU_DOMAIN",
                label="Domain",
                description="feishu for Feishu China, lark for Lark international.",
                placeholder="feishu",
            ),
            FieldSpec(
                key="FEISHU_CONNECTION_MODE",
                label="Connection mode",
                description="websocket (recommended) or webhook.",
                placeholder="websocket",
            ),
            FieldSpec(
                key="FEISHU_ENCRYPT_KEY",
                label="Encrypt key",
                description="Only needed for webhook mode with encryption enabled.",
                type="secret",
            ),
            FieldSpec(
                key="FEISHU_VERIFICATION_TOKEN",
                label="Verification token",
                description="Only needed for webhook mode.",
                type="secret",
            ),
        ),
    ),
    PlatformSpec(
        id="wecom",
        name="WeCom (group bot)",
        description="Run Spark as a WeCom (Enterprise WeChat) AI bot over WebSocket.",
        help_text=(
            "In the WeCom Admin Console create an AI Bot and copy its Bot ID and "
            "Secret — no public endpoint is needed."
        ),
        setup_guide_url="https://work.weixin.qq.com/",
        enabled_env="WECOM_ENABLED",
        required=(
            FieldSpec(key="WECOM_BOT_ID", label="Bot ID", description="From your WeCom AI Bot."),
            FieldSpec(
                key="WECOM_SECRET",
                label="Secret",
                description="From your WeCom AI Bot.",
                type="secret",
            ),
        ),
        recommended=(
            _allowlist("WECOM_ALLOWED_USERS"),
            _home_channel("WECOM_HOME_CHANNEL", "chat ID"),
        ),
        advanced=(
            FieldSpec(
                key="WECOM_WEBSOCKET_URL",
                label="WebSocket URL",
                description="Override the default WeCom WebSocket endpoint.",
            ),
        ),
    ),
    PlatformSpec(
        id="wecom_callback",
        name="WeCom (self-built app)",
        description="Connect a WeCom self-built app to Spark via callback URL.",
        help_text=(
            "Create a self-built app in the WeCom Admin Console, configure its receive-message "
            "callback to point at this server, and copy the Corp ID, Corp Secret, Token, and "
            "EncodingAESKey."
        ),
        setup_guide_url="https://work.weixin.qq.com/",
        enabled_env="WECOM_CALLBACK_ENABLED",
        required=(
            FieldSpec(
                key="WECOM_CALLBACK_CORP_ID",
                label="Corp ID",
                description="Shown at the top of the WeCom admin console.",
            ),
            FieldSpec(
                key="WECOM_CALLBACK_CORP_SECRET",
                label="Corp secret",
                description="Secret for your self-built application.",
                type="secret",
            ),
        ),
        recommended=(
            FieldSpec(
                key="WECOM_CALLBACK_AGENT_ID",
                label="Agent ID",
                description="The Agent ID of your self-built application.",
            ),
            FieldSpec(
                key="WECOM_CALLBACK_TOKEN",
                label="Callback token",
                description="From the WeCom callback configuration.",
                type="secret",
            ),
            FieldSpec(
                key="WECOM_CALLBACK_ENCODING_AES_KEY",
                label="Encoding AES key",
                description="From the WeCom callback configuration.",
                type="secret",
            ),
        ),
        advanced=(
            FieldSpec(
                key="WECOM_CALLBACK_PORT",
                label="Callback server port",
                description="Port the local HTTP callback server listens on.",
                type="number",
                placeholder="8645",
            ),
            _allowlist("WECOM_CALLBACK_ALLOWED_USERS"),
        ),
    ),
    PlatformSpec(
        id="weixin",
        name="WeChat / Weixin",
        description="Connect a personal WeChat account through the iLink Bot API.",
        help_text=(
            "Run `spark gateway setup` and choose Weixin to complete the QR-based pairing — "
            "Spark stores the returned account ID and token here automatically."
        ),
        setup_guide_url="https://developers.weixin.qq.com/",
        enabled_env="WEIXIN_ENABLED",
        required=(
            FieldSpec(
                key="WEIXIN_ACCOUNT_ID",
                label="Account ID",
                description="Issued during Weixin pairing.",
            ),
            FieldSpec(
                key="WEIXIN_TOKEN",
                label="Token",
                description="Issued during Weixin pairing.",
                type="secret",
            ),
        ),
        recommended=(
            _allowlist("WEIXIN_ALLOWED_USERS"),
            _home_channel("WEIXIN_HOME_CHANNEL", "chat ID"),
        ),
        advanced=(
            FieldSpec(
                key="WEIXIN_BASE_URL",
                label="API base URL",
                description="Override the iLink Bot API base URL.",
            ),
            FieldSpec(
                key="WEIXIN_DM_POLICY",
                label="DM policy",
                description="pairing, open, allowlist, or disabled.",
                placeholder="pairing",
            ),
            FieldSpec(
                key="WEIXIN_GROUP_POLICY",
                label="Group policy",
                description="How group messages are handled.",
            ),
        ),
    ),
    PlatformSpec(
        id="qqbot",
        name="QQ Bot",
        description="Run Spark as an official QQ bot (C2C, group, and guild messages).",
        help_text=(
            "Register a QQ Bot application at q.qq.com, copy its App ID and App Secret, "
            "and enable the message intents you need."
        ),
        setup_guide_url="https://q.qq.com",
        enabled_env="QQBOT_ENABLED",
        required=(
            FieldSpec(key="QQ_APP_ID", label="App ID", description="From your QQ Bot application page."),
            FieldSpec(
                key="QQ_CLIENT_SECRET",
                label="App secret",
                description="From your QQ Bot application page.",
                type="secret",
            ),
        ),
        recommended=(
            _allowlist("QQ_ALLOWED_USERS", "user OpenIDs"),
            _home_channel("QQ_HOME_CHANNEL", "OpenID"),
        ),
    ),
    PlatformSpec(
        id="webhook",
        name="Webhooks",
        description="Receive inbound HTTP webhooks and route them to Spark.",
        help_text=(
            "Enable the webhook listener and point external services at it. "
            "Per-route secrets can be configured in config.yaml under platforms.webhook."
        ),
        setup_guide_url="",
        enabled_env="WEBHOOK_ENABLED",
        enabled_env_is_native=True,
        recommended=(
            FieldSpec(
                key="WEBHOOK_PORT",
                label="Listener port",
                description="Port the webhook HTTP listener binds to.",
                type="number",
            ),
            FieldSpec(
                key="WEBHOOK_SECRET",
                label="Shared secret",
                description="Default secret required on inbound webhook requests.",
                type="secret",
            ),
        ),
    ),
    PlatformSpec(
        id="api_server",
        name="API server",
        description="OpenAI-compatible HTTP API for talking to Spark programmatically.",
        help_text=(
            "Enable the API server and set an API key — clients authenticate with it "
            "as a Bearer token against the OpenAI-compatible endpoints."
        ),
        setup_guide_url="",
        enabled_env="API_SERVER_ENABLED",
        enabled_env_is_native=True,
        recommended=(
            FieldSpec(
                key="API_SERVER_KEY",
                label="API key",
                description="Key clients must present to use the API.",
                type="secret",
            ),
        ),
        advanced=(
            FieldSpec(
                key="API_SERVER_HOST",
                label="Bind host",
                description="Interface the API server listens on.",
                placeholder="127.0.0.1",
            ),
            FieldSpec(
                key="API_SERVER_PORT",
                label="Port",
                description="Port the API server listens on.",
                type="number",
                placeholder="8642",
            ),
            FieldSpec(
                key="API_SERVER_CORS_ORIGINS",
                label="CORS origins",
                description="Comma-separated origins allowed to call the API from browsers.",
            ),
            FieldSpec(
                key="API_SERVER_MODEL_NAME",
                label="Model name",
                description="Model name advertised by the OpenAI-compatible endpoint.",
            ),
        ),
    ),
)


PLATFORM_SPECS: dict[str, PlatformSpec] = {spec.id: spec for spec in _SPECS}


def all_platform_specs() -> tuple[PlatformSpec, ...]:
    """All platform specs, in display order."""
    return _SPECS


def get_platform_spec(platform_id: str) -> PlatformSpec | None:
    """Look up one platform spec by id (``None`` for unknown ids)."""
    return PLATFORM_SPECS.get(platform_id)
