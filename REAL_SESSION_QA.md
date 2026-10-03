# Real Browser Session QA

This stage validates the agent against the user's own authenticated browser sessions.

## Safety

- The runner never submits an application.
- Login credentials are entered directly into the browser, never into config files or chat.
- CAPTCHA, OTP, authenticator-app prompts, security keys and identity checks are completed manually.
- Browser session files stay under the local ignored profile directory.
- QA results are stored locally under `data/`, which is ignored by Git.

## One-time local setup

Create and activate a Python virtual environment, then install Playwright locally:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install playwright
python -m playwright install chromium
```

Playwright and Chromium run locally. No paid API or paid model is required.

## First portal login

Start with LinkedIn:

```bash
python src/browser_qa.py --portal linkedin --login-only
```

A browser window opens using the persistent `browser-profile/` directory.

Log in directly in that browser. Complete any challenge manually. Return to the terminal and press Enter when fully logged in.

Then validate Naukri:

```bash
python src/browser_qa.py --portal naukri --login-only
```

## Validate all authenticated portals

After one-time login/session creation:

```bash
python src/browser_qa.py --portal all --login-only
```

The local status file is:

```text
data/browser_qa_status.json
```

Possible statuses:

- `SESSION_CONFIRMED`
- `LOGIN_REQUIRED`
- `HUMAN_ACTION_REQUIRED`
- `SESSION_UNVERIFIED`

`SESSION_UNVERIFIED` is intentionally fail-closed. It means the generic probe could not prove login and the portal needs a portal-specific login detector.

## Search probe

Once a portal is confirmed:

```bash
python src/browser_qa.py \
  --portal linkedin \
  --query "Customer Success Manager" \
  --location "India"
```

For international validation, examples include:

```bash
python src/browser_qa.py --portal linkedin --query "Technical Account Manager" --location "United Kingdom"
python src/browser_qa.py --portal linkedin --query "Customer Success Manager" --location "Singapore"
```

The runner still does not click Apply or Submit.
