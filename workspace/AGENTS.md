# Workspace Agent Rules

This workspace contains a local browser automation harness at:

- `C:\Users\user\Documents\ZeroFucks\browser-harness`

## Browser-First Routing

If the user asks to open a site, click, type, send a message, submit a form, or interact with a logged-in website, prefer the local `browser-harness` setup before checking Playwright or generic workspace browser dependencies.

Strong examples:

- Telegram Web
- Gmail, Google Calendar, Google Docs, Drive
- WordPress admin on arbitrary domains
- FASTPANEL and hosting/admin panels
- GitHub UI tasks in the user's logged-in browser

## Read Order For Browser Tasks

Before acting on a browser task, read:

1. `C:\Users\user\Documents\ZeroFucks\browser-harness\install.md` for first-time setup or reconnect
2. `C:\Users\user\Documents\ZeroFucks\browser-harness\SKILL.md` for normal usage
3. `C:\Users\user\Documents\ZeroFucks\browser-harness\helpers.py` for the actual callable surface

## Expected Behavior

- Use the user's real Chrome when possible.
- Activate setup or verification tabs so the user can see them.
- Do not start with Playwright probing if the task is clearly a real-browser task and `browser-harness` is available.
- Contribute durable lessons back into `browser-harness\domain-skills\` or `browser-harness\interaction-skills\` instead of leaving the knowledge only in the chat.
