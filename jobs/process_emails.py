"""Worker entry point for a Render Cron Job or local scheduler."""
from email_notifications import process_email_queue

if __name__ == '__main__':
    sent, failed = process_email_queue(limit=10)
    print(f'Merco email queue: sent={sent} failed={failed}')
