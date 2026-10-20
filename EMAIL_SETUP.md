# Enabling Email Notifications (Gmail SMTP)

SmartAssist sends email when an application's status changes (approved, rejected,
and so on). The code for this is already in place. If no email arrives, the cause
is almost always the **credentials**, which are read from environment variables
and are empty by default.

---

## Why nothing is being sent

`smartassist/settings.py` reads the Gmail account from the environment:

```python
EMAIL_HOST_USER     = os.getenv('EMAIL_HOST_USER', '')       # empty if not exported
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')   # empty if not exported
```

If those two variables are not set, Django tries to log in to Gmail with an empty
username and password. Gmail rejects the attempt, the send fails, and the
application keeps working normally — so the failure is easy to miss.

Run this to see exactly where you stand:

```bash
python manage.py send_test_email
```

It prints the resolved configuration and lists anything that is missing.

---

## Step 1 — Turn on 2-Step Verification

Gmail will not accept a normal account password from an application. Go to
<https://myaccount.google.com/security> and enable **2-Step Verification**.
The App Password option does not exist until this is on.

## Step 2 — Create an App Password

1. Open <https://myaccount.google.com/apppasswords>
2. Give it a name, e.g. `SmartAssist`
3. Click **Create**
4. Google shows a 16-character password like `abcd efgh ijkl mnop`

Copy it. You will not be able to see it again. This is **not** your normal Gmail
password — using your normal password produces the error `534`.

## Step 3 — Export the two variables

```bash
export EMAIL_HOST_USER="yourgmail@gmail.com"
export EMAIL_HOST_PASSWORD="abcdefghijklmnop"
```

Remove the spaces from the App Password. To make this permanent, add the two
lines to `~/.bashrc` (Linux) or `~/.zshrc` (macOS), then open a new terminal.

Note: the project has no `.env` auto-loading, so putting them in a `.env` file
does nothing on its own.

## Step 4 — Restart the server

Environment variables are read once, at startup. Stop the server with `Ctrl+C`
and start it again:

```bash
python manage.py runserver
```

## Step 5 — Verify

```bash
python manage.py send_test_email yourgmail@gmail.com
```

A successful run prints `Sent. Check the inbox (and the spam folder).`

Then test the real flow: log in as an admin, open an application, and change its
status. The farmer receives an email, and the admin sees either a success message
or a warning explaining why the email could not be sent.

---

## Troubleshooting

| Message | Cause | Fix |
| --- | --- | --- |
| `535 Username and Password not accepted` | Wrong App Password, or 2-Step Verification is off | Create a fresh App Password (Step 2) |
| `534` | You used your normal Gmail password | Use an App Password instead |
| `Timeout` / `Connection refused` | Port 465 is blocked on your network | Switch to port 587: set `EMAIL_PORT = 587`, `EMAIL_USE_TLS = True`, `EMAIL_USE_SSL = False` |
| Name resolution / DNS error | The machine has no internet access | Check the network connection |
| `EMAIL_HOST_USER is empty` | The variable was not exported, or the server was not restarted | Repeat Steps 3 and 4 |
| Email lands in spam | Sent through a personal Gmail account | Expected; see the note below |

---

## Where the email is sent from in the code

The farmer's address is chosen as:

1. the address typed on the application (`ApplicationRequest.email`), then
2. the address on the account (`User.email`)

If neither exists, the notification is still stored in the app but no email is
sent, and the admin is told why.

Three events trigger an email:

| Event | View | Message |
| --- | --- | --- |
| Application submitted | `apply_for_assistance` | "Application Submitted" |
| Status changed (approve/reject) | `update_application_status` | "Application Status Updated: <status>" |
| Applied on the farmer's behalf | `apply_scheme_admin` | "Scheme Applied" |

---

## Limits to be aware of

A personal Gmail account can send roughly **500 messages per day**, and mail sent
through it is more likely to be filtered as spam. That is fine for development
and demos.

For a real deployment, point the same four settings at a transactional provider
such as Amazon SES, Brevo or SendGrid. The application code does not change — only
`EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`/`EMAIL_USE_SSL`, `EMAIL_HOST_USER`
and `EMAIL_HOST_PASSWORD`.

---

## What changed in the code

| File | Change |
| --- | --- |
| `farmers/management/commands/send_test_email.py` | New: diagnoses the configuration and sends a test message |
| `farmers/emails.py` | `notify()` now records whether the send succeeded, and the reason if it did not |
| `farmers/views.py` | When an email fails, the admin now sees a warning instead of silent success |
| `templates/base.html` | Django messages (success/warning/error) are now displayed; previously they were queued but never shown |

No database migration is required.
