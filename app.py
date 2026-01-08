# AI Voice Bot Backend - Twilio Integration
# This connects to Twilio and handles incoming calls with AI

from flask import Flask, request, jsonify
from twilio.twiml.voice_response import VoiceResponse, Gather
from twilio.rest import Client
import openai
import os
from datetime import datetime
import json

app = Flask(__name__)

# Configuration - Add your credentials here
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID', 'your_account_sid_here')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN', 'your_auth_token_here')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER', '+44XXXXXXXXXX')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', 'your_openai_key_here')

# Initialize clients
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
openai.api_key = OPENAI_API_KEY

# In-memory storage for call data (use a database in production)
call_data = {}
conversations = {}

# Emergency keywords
EMERGENCY_KEYWORDS = ['burst', 'flooding', 'leak', 'emergency', 'urgent', 'water everywhere']

def detect_emergency(text):
    """Check if the call contains emergency keywords"""
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in EMERGENCY_KEYWORDS)

def get_ai_response(conversation_history, user_input):
    """Get AI response using OpenAI"""
    
    system_prompt = """You are a professional receptionist for a plumbing business. 
    Your job is to:
    1. Greet callers warmly
    2. Ask about their plumbing issue
    3. Collect their name, phone number (if different from caller ID), and address
    4. Ask about their preferred appointment time
    5. Confirm the booking
    6. Be empathetic if it's an emergency
    
    Keep responses SHORT (1-2 sentences max) since this is a phone call.
    Always be professional, helpful, and efficient.
    
    If they mention emergency keywords like 'burst pipe', 'flooding', 'leak', prioritize them immediately.
    """
    
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_input})
    
    response = openai.chat.completions.create(
        model="gpt-4",
        messages=messages,
        max_tokens=100,
        temperature=0.7
    )
    
    return response.choices[0].message.content

def extract_booking_info(conversation_text):
    """Use AI to extract booking details from conversation"""
    
    prompt = f"""Extract the following information from this phone conversation:
    - Customer name
    - Phone number (if mentioned)
    - Address
    - Issue/problem description
    - Preferred appointment time
    - Is this an emergency? (yes/no)
    
    Conversation:
    {conversation_text}
    
    Return as JSON with keys: name, phone, address, issue, appointment_time, is_emergency
    If information is missing, use "Not provided" as the value.
    """
    
    response = openai.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=200
    )
    
    try:
        return json.loads(response.choices[0].message.content)
    except:
        return {
            "name": "Not provided",
            "phone": "Not provided",
            "address": "Not provided",
            "issue": "Not provided",
            "appointment_time": "Not provided",
            "is_emergency": "no"
        }

@app.route('/voice', methods=['POST'])
def voice():
    """Handle incoming calls"""
    response = VoiceResponse()
    
    # Get caller information
    from_number = request.form.get('From')
    call_sid = request.form.get('CallSid')
    
    # Initialize conversation for this call
    if call_sid not in conversations:
        conversations[call_sid] = []
        call_data[call_sid] = {
            'from': from_number,
            'started_at': datetime.now().isoformat(),
            'conversation': []
        }
    
    # Initial greeting
    gather = Gather(
        input='speech',
        action='/process_speech',
        method='POST',
        speech_timeout='auto',
        language='en-GB'
    )
    
    gather.say(
        "Hello! Thank you for calling. How can I help you today?",
        voice='Polly.Amy',
        language='en-GB'
    )
    
    response.append(gather)
    
    # If no input, try again
    response.say("I didn't hear anything. Please give us a call back.", voice='Polly.Amy', language='en-GB')
    
    return str(response)

@app.route('/process_speech', methods=['POST'])
def process_speech():
    """Process speech input and generate AI response"""
    response = VoiceResponse()
    
    call_sid = request.form.get('CallSid')
    speech_result = request.form.get('SpeechResult', '')
    
    # Store the user's input
    conversations[call_sid].append({"role": "user", "content": speech_result})
    call_data[call_sid]['conversation'].append(f"Customer: {speech_result}")
    
    # Check for emergency
    is_emergency = detect_emergency(speech_result)
    if is_emergency:
        call_data[call_sid]['is_emergency'] = True
    
    # Get AI response
    ai_response = get_ai_response(conversations[call_sid], speech_result)
    conversations[call_sid].append({"role": "assistant", "content": ai_response})
    call_data[call_sid]['conversation'].append(f"Bot: {ai_response}")
    
    # Check if we have enough information to book
    conversation_length = len(conversations[call_sid])
    
    if conversation_length >= 6:  # After 3 exchanges, try to wrap up
        # Extract booking information
        conversation_text = "\n".join(call_data[call_sid]['conversation'])
        booking_info = extract_booking_info(conversation_text)
        
        # Save the booking
        call_data[call_sid]['booking_info'] = booking_info
        
        # Confirm and end call
        response.say(
            f"Perfect! I've got all your details. We'll see you at your appointment. "
            f"You'll receive a confirmation SMS shortly. Thank you for calling!",
            voice='Polly.Amy',
            language='en-GB'
        )
        
        # Send SMS confirmation (optional)
        send_confirmation_sms(call_sid)
        
        # Save to your dashboard database here
        save_to_dashboard(call_sid)
        
        response.hangup()
    else:
        # Continue conversation
        gather = Gather(
            input='speech',
            action='/process_speech',
            method='POST',
            speech_timeout='auto',
            language='en-GB'
        )
        
        gather.say(ai_response, voice='Polly.Amy', language='en-GB')
        response.append(gather)
    
    return str(response)

@app.route('/call_status', methods=['POST'])
def call_status():
    """Handle call status updates"""
    call_sid = request.form.get('CallSid')
    call_status = request.form.get('CallStatus')
    
    if call_sid in call_data:
        call_data[call_sid]['status'] = call_status
        call_data[call_sid]['ended_at'] = datetime.now().isoformat()
    
    return jsonify({'status': 'ok'})

def send_confirmation_sms(call_sid):
    """Send SMS confirmation to customer"""
    data = call_data.get(call_sid, {})
    booking_info = data.get('booking_info', {})
    
    customer_phone = booking_info.get('phone', data.get('from'))
    
    if customer_phone and customer_phone != "Not provided":
        try:
            message = twilio_client.messages.create(
                body=f"Thanks for booking with us! Your appointment is scheduled for {booking_info.get('appointment_time')}. "
                     f"Issue: {booking_info.get('issue')}. We'll see you soon!",
                from_=TWILIO_PHONE_NUMBER,
                to=customer_phone
            )
            print(f"SMS sent: {message.sid}")
        except Exception as e:
            print(f"SMS Error: {e}")

def save_to_dashboard(call_sid):
    """Save call data to your dashboard database"""
    data = call_data.get(call_sid, {})
    booking_info = data.get('booking_info', {})
    
    # Calculate call duration
    started = datetime.fromisoformat(data.get('started_at', datetime.now().isoformat()))
    ended = datetime.fromisoformat(data.get('ended_at', datetime.now().isoformat()))
    duration = str(ended - started).split('.')[0]
    
    # Format data for dashboard
    dashboard_data = {
        'clientName': booking_info.get('name', 'Unknown'),
        'phone': booking_info.get('phone', data.get('from', 'Unknown')),
        'issue': booking_info.get('issue', 'Not specified'),
        'urgency': 'emergency' if data.get('is_emergency') or booking_info.get('is_emergency') == 'yes' else 'normal',
        'appointmentTime': booking_info.get('appointment_time', 'Not scheduled'),
        'status': 'urgent' if data.get('is_emergency') else 'booked',
        'duration': duration,
        'transcript': '\n'.join(data.get('conversation', []))
    }
    
    # Here you would save to your actual database
    # For now, just print it
    print(f"Saving to dashboard: {json.dumps(dashboard_data, indent=2)}")
    
    # In production, you'd do something like:
    # database.save_call(dashboard_data)
    # or send to your React dashboard API endpoint

@app.route('/api/calls', methods=['GET'])
def get_calls():
    """API endpoint to retrieve call data for dashboard"""
    calls = []
    for call_sid, data in call_data.items():
        booking_info = data.get('booking_info', {})
        calls.append({
            'id': call_sid,
            'clientName': booking_info.get('name', 'Unknown'),
            'phone': booking_info.get('phone', data.get('from', 'Unknown')),
            'issue': booking_info.get('issue', 'Not specified'),
            'urgency': 'emergency' if data.get('is_emergency') else 'normal',
            'appointmentTime': booking_info.get('appointment_time', 'Not scheduled'),
            'status': data.get('status', 'in-progress'),
            'timestamp': data.get('started_at'),
            'transcript': '\n'.join(data.get('conversation', []))
        })
    return jsonify(calls)

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

if __name__ == '__main__':
    # Run on port 5000
    print("AI Voice Bot Backend Starting...")
    print("Make sure to set your environment variables:")
    print("  - TWILIO_ACCOUNT_SID")
    print("  - TWILIO_AUTH_TOKEN")
    print("  - TWILIO_PHONE_NUMBER")
    print("  - OPENAI_API_KEY")
    app.run(host='0.0.0.0', port=5000, debug=True)
