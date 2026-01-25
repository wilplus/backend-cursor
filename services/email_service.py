import resend
from config import Config
import sentry_sdk

config = Config()

class EmailService:
    def __init__(self):
        # Set Resend API key (required for resend.Emails.send())
        if config.RESEND_API_KEY:
            resend.api_key = config.RESEND_API_KEY
        self.api_key_set = bool(config.RESEND_API_KEY)
    
    def send_admin_notification(
        self,
        user_id: str,
        session_id: str,
        recording_id: str,
        pre_answers: list,
        post_answers: list,
        transcript_preview: str,
        final_report: str,
        suggested_questions: list
    ):
        """
        Send admin notification email via Resend.
        Returns notification record data.
        """
        if not config.SEND_EMAILS:
            # In dev mode or if emails disabled, just return without sending
            return {
                "status": "pending",
                "sent": False
            }
        
        if not self.api_key_set:
            raise Exception("Resend API key not set")
        
        # Build email content (plain text)
        email_lines = [
            "New Speech Analysis Session Completed",
            "",
            "=== Pre-Recording Answers ===",
        ]
        
        for ans in pre_answers:
            question_text = ans.get("question_text", "Question")
            answer_text = ans.get("answer_text", "")
            email_lines.append(f"Q: {question_text}")
            email_lines.append(f"A: {answer_text}")
            email_lines.append("")
        
        email_lines.append("=== Post-Recording Answers ===")
        for ans in post_answers:
            question_text = ans.get("question_text", "Question")
            answer_text = ans.get("answer_text", "")
            email_lines.append(f"Q: {question_text}")
            email_lines.append(f"A: {answer_text}")
            email_lines.append("")
        
        email_lines.append("=== Transcript Preview ===")
        email_lines.append(transcript_preview)
        email_lines.append("")
        
        email_lines.append("=== Final Report ===")
        email_lines.append(final_report)
        email_lines.append("")
        
        email_lines.append("=== Suggested Questions ===")
        for q in suggested_questions:
            email_lines.append(f"[{q.get('tag', 'unknown')}] {q.get('question_text', '')}")
            email_lines.append(f"Rationale: {q.get('rationale', '')}")
            email_lines.append("")
        
        # Add feedback link
        # Format: https://app.willonski.com/recordings/{recording_id}/feedback?user_id={user_id}
        # Or: http://localhost:3000/recordings/{recording_id}/feedback?user_id={user_id} (dev)
        frontend_url = config.FRONTEND_URL
        feedback_url = f"{frontend_url}/recordings/{recording_id}/feedback?user_id={user_id}"
        
        email_lines.append("")
        email_lines.append("=== Provide Feedback ===")
        email_lines.append(f"Click here to provide feedback for this user:")
        email_lines.append(feedback_url)
        email_lines.append("")
        email_lines.append("Feedback will be used to personalize future analysis for this user.")
        
        email_body = "\n".join(email_lines)
        
        # Create HTML version with styled button
        html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background-color: #4F46E5; color: white; padding: 20px; border-radius: 5px 5px 0 0; }}
        .content {{ background-color: #f9fafb; padding: 20px; border: 1px solid #e5e7eb; }}
        .button {{ display: inline-block; background-color: #4F46E5; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; margin: 20px 0; }}
        .button:hover {{ background-color: #4338CA; }}
        .info {{ background-color: white; padding: 15px; margin: 10px 0; border-radius: 5px; border-left: 4px solid #4F46E5; }}
        .footer {{ text-align: center; color: #6b7280; font-size: 12px; margin-top: 20px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>New Speech Analysis Session Completed</h1>
        </div>
        <div class="content">
            <div class="info">
                <strong>Recording ID:</strong> {recording_id}<br>
                <strong>User ID:</strong> {user_id}
            </div>
            
            <div class="info">
                <strong>Pre-Recording Answers:</strong><br>
                {'<br>'.join([f"Q: {ans.get('question_text', 'Question')}<br>A: {ans.get('answer_text', '')}" for ans in pre_answers])}
            </div>
            
            <div class="info">
                <strong>Post-Recording Answers:</strong><br>
                {'<br>'.join([f"Q: {ans.get('question_text', 'Question')}<br>A: {ans.get('answer_text', '')}" for ans in post_answers])}
            </div>
            
            <div class="info">
                <strong>Transcript Preview:</strong><br>
                {transcript_preview[:300]}...
            </div>
            
            <div class="info">
                <strong>Final Report:</strong><br>
                {final_report}
            </div>
            
            <div class="info">
                <strong>Suggested Questions:</strong><br>
                {'<br>'.join([f"[{q.get('tag', 'unknown')}] {q.get('question_text', '')}<br>Rationale: {q.get('rationale', '')}" for q in suggested_questions])}
            </div>
            
            <div style="text-align: center; margin: 30px 0;">
                <a href="{feedback_url}" class="button">Provide Feedback</a>
            </div>
        </div>
        <div class="footer">
            <p>This is an automated notification from Willab.</p>
            <p>Click the button above to provide feedback and improve AI analysis for this user.</p>
        </div>
    </div>
</body>
</html>
"""
        
        # Prepare payload for database
        payload = {
            "user_id": user_id,
            "session_id": session_id,
            "recording_id": recording_id,
            "pre_answers": pre_answers,
            "post_answers": post_answers,
            "transcript_preview": transcript_preview,
            "final_report": final_report,
            "suggested_questions": suggested_questions
        }
        
        try:
            # Send email using resend.Emails.send() with both text and HTML
            params = {
                "from": config.RESEND_FROM_EMAIL,
                "to": [config.ADMIN_EMAIL],
                "subject": f"Speech Analysis Session Completed - Session {session_id[:8]}",
                "text": email_body,
                "html": html_body
            }
            
            email_response = resend.Emails.send(params)
            
            return {
                "status": "sent",
                "sent": True,
                "email_id": email_response.get("id") if email_response else None,
                "payload": payload
            }
        except Exception as e:
            sentry_sdk.capture_exception(e)
            return {
                "status": "failed",
                "sent": False,
                "error": str(e),
                "payload": payload
            }

# Singleton instance
email_service = EmailService()
