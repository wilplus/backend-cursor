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
        # You can customize this URL based on your admin dashboard
        admin_dashboard_url = config.ADMIN_DASHBOARD_URL if hasattr(config, 'ADMIN_DASHBOARD_URL') else "https://your-admin-dashboard.com"
        feedback_url = f"{admin_dashboard_url}/recordings/{recording_id}/feedback?user_id={user_id}"
        
        email_lines.append("")
        email_lines.append("=== Provide Feedback ===")
        email_lines.append(f"Click here to provide feedback for this user: {feedback_url}")
        email_lines.append("")
        email_lines.append("Feedback will be used to personalize future analysis for this user.")
        
        email_body = "\n".join(email_lines)
        
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
            # Send email using resend.Emails.send()
            params = {
                "from": config.RESEND_FROM_EMAIL,
                "to": [config.ADMIN_EMAIL],
                "subject": f"Speech Analysis Session Completed - Session {session_id[:8]}",
                "text": email_body
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
