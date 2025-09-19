from django.conf import settings
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
import logging

logger = logging.getLogger(__name__)

class SMSNotificationService:
    def __init__(self):
        # Check if Twilio credentials are available
        account_sid = getattr(settings, 'TWILIO_ACCOUNT_SID', None)
        auth_token = getattr(settings, 'TWILIO_AUTH_TOKEN', None)
        self.from_number = getattr(settings, 'TWILIO_PHONE_NUMBER', None)
        
        if account_sid and auth_token:
            try:
                self.client = Client(account_sid, auth_token)
                logger.info("SMS notification service initialized with Twilio credentials")
            except Exception as e:
                logger.error(f"Failed to initialize Twilio client: {str(e)}")
                self.client = None
        else:
            logger.warning("Twilio credentials not found - SMS notifications disabled")
            self.client = None

    def send_notification(self, to_number, message):
        """
        Send SMS notification using Twilio.
        Handles rate limiting and other errors gracefully.
        """
        if not self.client:
            logger.warning(f"SMS client not available - skipping notification to {to_number}")
            return False
            
        try:
            message = self.client.messages.create(
                body=message,
                from_=self.from_number,
                to=to_number
            )
            logger.info(f"SMS sent successfully to {to_number}. SID: {message.sid}")
            return True
        except TwilioRestException as e:
            if e.code == 63038:  # Rate limit exceeded
                logger.warning(f"Twilio rate limit exceeded for number {to_number}. Message not sent.")
            else:
                logger.error(f"Error sending SMS to {to_number}: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending SMS to {to_number}: {str(e)}")
            return False

class WhatsAppNotificationService:
    def __init__(self):
        # Check if Twilio credentials are available
        account_sid = getattr(settings, 'TWILIO_ACCOUNT_SID', None)
        auth_token = getattr(settings, 'TWILIO_AUTH_TOKEN', None)
        self.from_number = getattr(settings, 'TWILIO_PHONE_NUMBER', None)
        
        if account_sid and auth_token:
            try:
                self.client = Client(account_sid, auth_token)
                logger.info("WhatsApp notification service initialized with Twilio credentials")
            except Exception as e:
                logger.error(f"Failed to initialize Twilio client for WhatsApp: {str(e)}")
                self.client = None
        else:
            logger.warning("Twilio credentials not found - WhatsApp notifications disabled")
            self.client = None

    def send_notification(self, to_number, message):
        if not self.client:
            logger.warning(f"WhatsApp client not available - skipping notification to {to_number}")
            return False
            
        try:
            # Format the phone numbers for WhatsApp
            # Ensure from_number has country code
            from_number = f"whatsapp:{self.from_number.lstrip('+')}"
            # Ensure to_number has country code and no plus sign
            to_number = f"whatsapp:{to_number.lstrip('+')}"
            
            logger.info(f"Sending WhatsApp message from {from_number} to {to_number}")
            
            message = self.client.messages.create(
                body=message,
                from_=from_number,
                to=to_number
            )
            logger.info(f"WhatsApp message sent successfully: {message.sid}")
            return True
        except Exception as e:
            logger.error(f"Error sending WhatsApp message: {str(e)}")
            return False 