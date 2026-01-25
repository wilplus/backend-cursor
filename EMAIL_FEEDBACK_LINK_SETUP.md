# Email Feedback Link Setup

## ✅ Changes Made

1. **Updated `config.py`** - Added `FRONTEND_URL` configuration
2. **Updated `services/email_service.py`** - Updated feedback link format and added HTML email

## 🔧 Environment Variables

### For Development (localhost:3000)

Add to your `.env` file or Railway environment variables:

```bash
FRONTEND_URL=http://localhost:3000
```

### For Production (app.willonski.com)

Add to Railway environment variables:

```bash
FRONTEND_URL=https://app.willonski.com
```

## 📧 Email Link Format

The feedback link in admin emails will be:

**Development:**
```
http://localhost:3000/recordings/{recording_id}/feedback?user_id={user_id}
```

**Production:**
```
https://app.willonski.com/recordings/{recording_id}/feedback?user_id={user_id}
```

## ✨ Features Added

1. **HTML Email** - Beautiful styled email with button
2. **Plain Text Fallback** - Plain text version for email clients that don't support HTML
3. **Correct Link Format** - Matches frontend route structure

## 🧪 Testing

1. **Set `FRONTEND_URL`** in Railway:
   - Development: `http://localhost:3000`
   - Production: `https://app.willonski.com`

2. **Set `SEND_EMAILS=true`** in Railway

3. **Upload a recording** and submit post-answers

4. **Check admin email** - Should see:
   - Styled HTML email with "Provide Feedback" button
   - Link format: `https://app.willonski.com/recordings/{id}/feedback?user_id={id}`

5. **Click the link** - Should open feedback form in frontend

## 📝 Example Email Link

```
https://app.willonski.com/recordings/dfc436db-c73c-49de-a3c3-d308674ff611/feedback?user_id=5402278f-38f6-4538-8c1b-b65c6912f5da
```

This link will work once the frontend implements the `/recordings/[recordingId]/feedback` page.

## ✅ Checklist

- [x] Updated config to use `FRONTEND_URL`
- [x] Updated email service to use correct link format
- [x] Added HTML email with styled button
- [ ] Set `FRONTEND_URL` in Railway (you need to do this)
- [ ] Test email link in development
- [ ] Test email link in production

---

**Next Step:** Set `FRONTEND_URL` environment variable in Railway! 🚀
