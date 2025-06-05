from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory, session, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import os
from sqlalchemy.orm import relationship
from datetime import datetime
import PyPDF2
from werkzeug.utils import secure_filename
from flask_migrate import Migrate
from flask_moment import Moment
import json
import random
import requests
from datetime import datetime
import uuid
from urllib.parse import urlencode
import copy
import google.generativeai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from dotenv import load_dotenv
from functools import wraps
import json
import networkx as nx
from networkx.readwrite import json_graph
import matplotlib.pyplot as plt
import io
import base64
from PIL import Image
import google.generativeai as genai
from datetime import datetime

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
if not os.path.exists('instance'):
    os.makedirs('instance')
app.config['SECRET_KEY'] = os.urandom(24)
# app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///forms.db'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///instance/form.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['GOOGLE_API_KEY'] = os.getenv('GOOGLE_API_KEY')  # Get API key from environment
app.config['RECAPTCHA_SITE_KEY'] = os.getenv('RECAPTCHA_SITE_KEY')
app.config['RECAPTCHA_SECRET_KEY'] = os.getenv('RECAPTCHA_SECRET_KEY')
app.config['RECAPTCHA_VERIFY_URL'] = 'https://www.google.com/recaptcha/api/siteverify'
app.jinja_env.filters['fromjson'] = json.loads

# Configure Google Generative AI with HTTP transport
try:
    google.generativeai.configure(
        api_key=app.config['GOOGLE_API_KEY'],
        transport='rest'  # Use REST transport instead of gRPC
    )
    print("Successfully configured Google Generative AI with REST transport")
except Exception as e:
    print(f"Error configuring Google Generative AI: {str(e)}")

# Create uploads directory if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize Flask-Moment for handling dates and times in templates
moment = Moment(app)

# Add context processor for current date
@app.context_processor
def inject_now():
    return {'now': datetime.now()}

# Add context processor for csrf_token
@app.context_processor
def inject_csrf_token():
    # This is a simple shim to avoid the csrf_token undefined error
    # We're using the _method approach for form security instead
    return {'csrf_token': lambda: 'dummy_token'}

db = SQLAlchemy(app)
migrate = Migrate(app, db)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
with app.app_context():
    db.create_all()
def fromjson_filter(s):
    try:
        return json.loads(s)
    except Exception:
        return []
app.jinja_env.filters['fromjson'] = fromjson_filter

def datetime_filter(date):
    if date:
        return date.strftime('%Y-%m-%d %H:%M:%S')
    return ''
app.jinja_env.filters['datetime'] = datetime_filter

# Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    forms = db.relationship('Form', backref='author', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Company(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    referral_code = db.Column(db.String(50), unique=True, nullable=False)
    forms = db.relationship('Form', backref='company', lazy=True)

class Form(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    score = db.Column(db.Integer, default=100)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', name='fk_form_user'), nullable=False)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id', name='fk_form_company'), nullable=True)
    questions = db.relationship('Question', backref='form', lazy=True, cascade='all, delete-orphan')
    responses = db.relationship('Response', backref='form', lazy=True, cascade='all, delete-orphan')
    is_closed = db.Column(db.Boolean, default=False)  # New field to track if the form is closed/expired
    requires_consent = db.Column(db.Boolean, default=True)  # Require privacy policy and terms consent
    
    # Quiz-related fields
    is_quiz = db.Column(db.Boolean, default=False)  # Is this form a quiz?
    passing_score = db.Column(db.Integer, default=0)  # Passing score percentage
    show_score = db.Column(db.Boolean, default=True)  # Whether to show score to respondents
    merged_url = db.Column(db.String(255), nullable=True, default='')

class SubQuestion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'), nullable=False)
    parent_option = db.Column(db.String(255), nullable=False)  # Which option this subquestion belongs to
    question_text = db.Column(db.String(500), nullable=False)
    question_type = db.Column(db.String(20), nullable=False)  # text, multiple_choice, checkbox
    options = db.Column(db.Text)  # JSON string for multiple choice/checkbox options
    required = db.Column(db.Boolean, default=False)
    order = db.Column(db.Integer, nullable=False)
    nesting_level = db.Column(db.Integer, default=1)  # 1 for first level, 2 for nested, etc.
    answers = relationship('SubQuestionAnswer', backref='subquestion', lazy=True, cascade='all, delete-orphan')
    
# Add this model for tracking postbacks
class PostbackTracking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, db.ForeignKey('form.id'), nullable=False)
    tracking_id = db.Column(db.String(100), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    transaction_count = db.Column(db.Integer, default=0)
    
    form = db.relationship('Form', backref='postback_tracking')

# Add this model for storing postback logs
class PostbackLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tracking_id = db.Column(db.String(100), nullable=False)
    transaction_id = db.Column(db.String(100), nullable=True)
    username = db.Column(db.String(100), nullable=True)
    user_id = db.Column(db.String(100), nullable=True)
    status = db.Column(db.String(50), nullable=True)
    payout = db.Column(db.Float, nullable=True)
    response_json = db.Column(db.Text, nullable=True)  # Store full response
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    ip_address = db.Column(db.String(50), nullable=True)

    def get_options(self):
        if self.options:
            try:
                return json.loads(self.options)
            except:
                return []
        return []
    
    def set_options(self, options):
        self.options = json.dumps(options)

class SubQuestionAnswer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    response_id = db.Column(db.Integer, db.ForeignKey('response.id'), nullable=False)
    subquestion_id = db.Column(db.Integer, db.ForeignKey('sub_question.id'), nullable=False)
    selected_option = db.Column(db.String(255), nullable=True)  # For multiple choice/checkbox
    answer_text = db.Column(db.Text, nullable=True)  # For text questions

# Modify the Question model to include relationship to SubQuestions
class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, db.ForeignKey('form.id'), nullable=False)
    question_text = db.Column(db.String(500), nullable=False)
    question_type = db.Column(db.String(20), nullable=False)  # text, multiple_choice, checkbox
    options = db.Column(db.Text)  # JSON string for multiple choice/checkbox options
    required = db.Column(db.Boolean, default=False)
    order = db.Column(db.Integer, nullable=False)
    
    # Quiz-related fields
    is_quiz_question = db.Column(db.Boolean, default=False)
    correct_answer = db.Column(db.Text, nullable=True)  # JSON string for correct answers
    points = db.Column(db.Integer, default=0)  # Points for correct answer
    feedback = db.Column(db.Text, nullable=True)  # Feedback for the question
    
    # Add relationship to subquestions
    subquestions = relationship('SubQuestion', backref='parent_question', lazy=True, 
                               cascade='all, delete-orphan')

    def get_options(self):
        import json
        if self.options:
            try:
                # Parse the JSON-encoded options
                options = json.loads(self.options)
                
                # Handle both old format (array of strings) and new format (array of objects)
                if options and isinstance(options, list):
                    # If first item is already an object, return as is
                    if isinstance(options[0], dict):
                        # Make sure each option has the required fields for media
                        for opt in options:
                            if 'media_type' not in opt:
                                opt['media_type'] = 'none'
                            if 'media_url' not in opt:
                                opt['media_url'] = None
                            if 'media_description' not in opt:
                                opt['media_description'] = None
                        return options
                    # Convert simple strings to objects with text property
                    else:
                        return [{'text': opt, 'media_type': 'none', 'media_url': None, 'media_description': None} for opt in options]
                return []
            except Exception as e:
                print(f"Error parsing options in get_options(): {str(e)}")
                return []
        return []

    def set_options(self, options):
        import json
        self.options = json.dumps(options)

# Update the Response model to include subquestion answers
class Response(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, db.ForeignKey('form.id'), nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id', name='fk_response_company'), nullable=True)
    user_id = db.Column(db.String(100), nullable=True)
    company_name = db.Column(db.String(200), nullable=True)
    answers = relationship('Answer', backref='response', lazy=True, cascade='all, delete-orphan')
    subquestion_answers = relationship('SubQuestionAnswer', backref='response', lazy=True, 
                                      cascade='all, delete-orphan')
    company = relationship('Company', backref='responses')
    # Add UTM tracking fields
    utm_source = db.Column(db.String(100), nullable=True)
    utm_medium = db.Column(db.String(100), nullable=True)
    utm_campaign = db.Column(db.String(100), nullable=True)
    utm_content = db.Column(db.String(100), nullable=True)
    utm_term = db.Column(db.String(100), nullable=True)
    # New field for device type
    device_type = db.Column(db.String(20), nullable=True)
    # Privacy and Terms consent
    has_consent = db.Column(db.Boolean, default=False)
    
    # Quiz-related fields
    score = db.Column(db.Integer, nullable=True)  # Quiz score (total points)
    max_score = db.Column(db.Integer, nullable=True)  # Maximum possible score
    passed = db.Column(db.Boolean, nullable=True)  # Whether the user passed
    status = db.Column(db.String(50), default="success")

class Answer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    response_id = db.Column(db.Integer, db.ForeignKey('response.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'), nullable=False)
    answer_text = db.Column(db.Text, nullable=False)
    # Add relationship to Question
    question = db.relationship('Question', backref='answers')

class PDFUpload(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    form_id = db.Column(db.Integer, db.ForeignKey('form.id'), nullable=True)
    user = db.relationship('User', backref='pdf_uploads')
    form = db.relationship('Form', backref='pdf_upload')

class FormTemplate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    questions = db.Column(db.Text)  # JSON string of questions
    category = db.Column(db.String(50))  # e.g., 'survey', 'registration', 'feedback'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_public = db.Column(db.Boolean, default=True)
    preview_image = db.Column(db.String(255), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    user = db.relationship('User', backref='templates')
    template_data = db.Column(db.Text, nullable=True)  # JSON string of complete template data

    def get_questions(self):
        try:
            return json.loads(self.questions) if self.questions else []
        except:
            return []

    def set_questions(self, questions):
        self.questions = json.dumps(questions)
        
    def get_template_data(self):
        """Get complete template data including questions and subquestions"""
        # Provide backward compatibility - if template_data field is empty, create from questions
        if not self.template_data:
            questions = self.get_questions()
            data = {
                'questions': questions,
                'subquestions': []
            }
            return json.dumps(data)
        return self.template_data
        
    def set_template_data(self, data):
        """Set template data. Accepts either JSON string or Python dict."""
        if isinstance(data, dict):
            self.template_data = json.dumps(data)
        else:
            self.template_data = data

class Geolocation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    response_id = db.Column(db.Integer, db.ForeignKey('response.id'), nullable=False)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    city = db.Column(db.String(100), nullable=True)
    region = db.Column(db.String(100), nullable=True)
    country = db.Column(db.String(100), nullable=True)
    ip_address = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    response = db.relationship('Response', backref='geolocation')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Routes

def generate_postback_url(form_id, user_id):
    # Generate a unique tracking ID
    tracking_id = str(uuid.uuid4())
    
    # Check if there's already a tracking for this form
    existing = PostbackTracking.query.filter_by(form_id=form_id).first()
    
    if existing:
        # Return existing tracking ID
        tracking_id = existing.tracking_id
    else:
        # Create new tracking record
        tracking = PostbackTracking(
            form_id=form_id,
            tracking_id=tracking_id
        )
        db.session.add(tracking)
        db.session.commit()
    
    # Build the postback URL
    base_url = "https://pepper-ads.com/postback"
    params = {
        'tracking_id': tracking_id,
        'user_id': user_id
    }
    
    return f"{base_url}?{urlencode(params)}"

# Add this function to save postback data to JSON file
def save_postback_to_json(postback_data):
    filename = 'postback_logs.json'
    
    # Try to read existing data
    try:
        with open(filename, 'r') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = []
        
    # Add timestamp to data
    postback_data['logged_at'] = datetime.utcnow().isoformat()
    
    # Append new data
    data.append(postback_data)
    
    # Write back to file
    with open(filename, 'w') as f:
        json.dump(data, f, indent=2)
    
    return True

# Add this function after existing imports
def extract_utm_parameters(request):
    """Extract all UTM parameters from a request"""
    utm_params = {}
    
    # Common UTM parameters to extract
    utm_fields = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content']
    
    for param in utm_fields:
        value = request.args.get(param)
        if value:
            utm_params[param] = value
    
    return utm_params
def detect_device_type(user_agent):
    """Detect if user is on mobile, tablet, or desktop based on user agent string"""
    user_agent = user_agent.lower()
    
    # Check for mobile devices first
    if any(word in user_agent for word in ['iphone', 'android', 'mobile', 'phone']):
        # Special check for tablets that also have "android" in their UA
        if any(word in user_agent for word in ['ipad', 'tablet']):
            return 'tablet'
        return 'mobile'
    
    # Check for tablets
    elif any(word in user_agent for word in ['ipad', 'tablet']):
        return 'tablet'
    
    # Default to desktop
    else:
        return 'desktop'
    
@app.route('/')
def index():
    # Extract UTM parameters and session ID
    utm_params = extract_utm_parameters(request)
    session_id = request.args.get('session_id')
    
    # Detect device type
    device_type = request.args.get('device')
    if not device_type:
        device_type = detect_device_type(request.user_agent.string)
    
    # Store UTM, session and device data in session if present
    if 'utm_source' in utm_params:
        session['utm_source'] = utm_params['utm_source']
        session['utm_data'] = utm_params
    
    if session_id:
        session['session_id'] = session_id
        
    # Store device type
    session['device_type'] = device_type
    
    # Check if there are form_id and user_id query parameters
    form_id = request.args.get('form_id')
    user_id = request.args.get('user_id')
    
    # If both parameters exist, try to show the form
    if form_id and user_id:
        try:
            form_id = int(form_id)
            user_id = int(user_id)
            
            # Check if the form exists and belongs to the specified user
            form = Form.query.filter_by(id=form_id, user_id=user_id).first()
            
            if form:
                # If found, redirect to the form view - ensure we don't lose UTM parameters
                return redirect(url_for('view_form', form_id=form_id))
            else:
                flash('Form not found or invalid user ID')
        except ValueError:
            flash('Invalid form ID or user ID')
    
    # If no parameters or invalid form, show the regular index page
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid email or password')
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered')
            return redirect(url_for('signup'))
            
        user = User(email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        login_user(user)
        return redirect(url_for('dashboard'))
    return render_template('signup.html')

@app.route('/dashboard')
@login_required
def dashboard():
    try:
        # Get user's forms
        forms = Form.query.filter_by(user_id=current_user.id).all()
        
        # Get predefined templates
        predefined_templates = FormTemplate.query.filter_by(is_public=True).all()
        
        # Get user's custom templates if they exist
        user_templates = []
        if hasattr(current_user, 'templates'):
            user_templates = current_user.templates
        
        # Combine user templates and predefined templates
        all_templates = list(user_templates) + list(predefined_templates)
        
        print(f"Forms: {len(forms)}, Templates: {len(all_templates)}")
        
        return render_template('dashboard.html', forms=forms, templates=all_templates)
    except Exception as e:
        print(f"Error in dashboard route: {str(e)}")
        return render_template('dashboard.html', forms=[], templates=[])

@app.route('/create_form', methods=['GET', 'POST'])
@login_required
def create_form():
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        requires_consent = 'requires_consent' in request.form
        score = request.form.get('score', 100)
        print("score=",score)
        # Create a new form
        form = Form(
            title=title,
            description=description,
            user_id=current_user.id,
            company_id=session.get('referral_company_id'),
            requires_consent=requires_consent,
            score=score
        )
        
        # Add form to database
        db.session.add(form)
        db.session.commit()
        
        # Clear referral from session after form creation
        session.pop('referral_company_id', None)
        
        return redirect(url_for('edit_form', form_id=form.id))
        
    return render_template('create_form.html')

@app.route('/form/<int:form_id>')
def view_form(form_id):
    form = Form.query.get_or_404(form_id)
    
    # Get all subquestions for this form
    subquestions = SubQuestion.query.join(Question).filter(Question.form_id == form_id).all()

    # Process each question to handle nested structures
    for question in form.questions:
        if question.question_type in ['radio', 'multiple_choice']:
            try:
                # Parse options with full nested structure
                question.nested_options = json.loads(question.options or '[]')
                
                # If options is a plain array, convert to nested format
                if question.nested_options and isinstance(question.nested_options[0], str):
                    question.nested_options = [{"text": opt, "subquestions": []} for opt in question.nested_options]
            except (json.JSONDecodeError, TypeError, IndexError):
                # Fallback for legacy data format
                try:
                    raw_options = question.get_options()
                    # Convert simple options to the nested format
                    question.nested_options = [
                        {"text": opt, "subquestions": []} 
                        for opt in raw_options if opt
                    ]
                except Exception:
                    # Last resort fallback
                    question.nested_options = []

    # Sort questions by order
    form.questions.sort(key=lambda q: q.order)
    
    # Generate iframe embed code
    if request.headers.get('X-Forwarded-Proto'):
        proto = request.headers.get('X-Forwarded-Proto')
    else:
        proto = 'https' if request.is_secure else 'http'
    
    host = request.host
    base_url = f"{proto}://{host}"
    
    # Create embed URL for iframe - using the ?embedded=true parameter like Google Forms
    embed_url = f"{base_url}/form/{form.id}/embed?embedded=true"
    
    # Generate iframe code that matches Google Forms style
    iframe_code = f'<iframe src="{embed_url}" width="640" height="382" frameborder="0" marginheight="0" marginwidth="0">Loading…</iframe>'
    
    # Add reCAPTCHA site key to template context
    return render_template('view_form.html', 
                         form=form, 
                         subquestions=subquestions, 
                         iframe_code=iframe_code, 
                         embed_url=embed_url, 
                         is_closed=form.is_closed,
#                         recaptcha_site_key=app.config['RECAPTCHA_SITE_KEY']
                        )

@app.route('/form/<int:form_id>/edit')
@login_required
def edit_form(form_id):
    form = Form.query.get_or_404(form_id)
    if form.user_id != current_user.id:
        return redirect(url_for('dashboard'))

    # decode JSON-encoded options into a new attribute
    for q in form.questions:
        try:
            q.parsed_options = json.loads(q.options) if q.options else []
        except ValueError:
            q.parsed_options = []

    return render_template('edit_form.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

# Helper function to export responses as JSON
def export_response_to_json(response, form):
    """
    Helper function to export a single response as JSON
    
    Args:
        response: The Response object to export
        form: The Form object the response belongs to
        
    Returns:
        dict: JSON-serializable dictionary of the response data
        str: Path to the saved JSON file
    """
    # Create response data structure
    response_data = {
        'response_id': response.id,
        'form_id': form.id,
        'form_title': form.title,
        'submitted_at': response.submitted_at.isoformat(),
        'utm_data': {
            'source': response.utm_source,
            'medium': response.utm_medium,
            'campaign': response.utm_campaign,
            'content': response.utm_content,
            'term': response.utm_term
        },
        'device_type': response.device_type,
        'company_id': response.company_id,
        'company_name': response.company.name if response.company else None,
        'answers': []
    }
    
    # Get all answers for this response
    for question in form.questions:
        answer = Answer.query.filter_by(
            response_id=response.id,
            question_id=question.id
        ).first()
        
        if answer:
            answer_data = {
                'question_id': question.id,
                'question_text': question.question_text,
                'question_type': question.question_type,
                'answer_text': answer.answer_text
            }
            
            # Get subquestion answers if applicable
            if question.question_type in ['radio', 'multiple_choice', 'checkbox']:
                # Get selected options
                selected_options = answer.answer_text.split(', ') if question.question_type == 'checkbox' else [answer.answer_text]
                
                # Get all subquestions for this question
                subquestions = SubQuestion.query.filter_by(question_id=question.id).all()
                
                subquestion_answers = []
                for subq in subquestions:
                    # Only include subquestions matching selected parent options
                    if any(opt in subq.parent_option for opt in selected_options):
                        sq_answer = SubQuestionAnswer.query.filter_by(
                            response_id=response.id,
                            subquestion_id=subq.id
                        ).first()
                        
                        if sq_answer:
                            subquestion_answers.append({
                                'subquestion_id': subq.id,
                                'subquestion_text': subq.question_text,
                                'subquestion_type': subq.question_type,
                                'parent_option': subq.parent_option,
                                'answer_text': sq_answer.answer_text
                            })
                
                # Add subquestion answers if any exist
                if subquestion_answers:
                    answer_data['subquestion_answers'] = subquestion_answers
            
            response_data['answers'].append(answer_data)
    
    # Create export directory if it doesn't exist
    export_path = os.path.join('exports', 'survey_responses')
    os.makedirs(export_path, exist_ok=True)
    
    # Create filename with form ID, response ID and timestamp
    timestamp = response.submitted_at.strftime('%Y%m%d%H%M%S')
    filename = f"response_{form.id}_{response.id}_{timestamp}.json"
    file_path = os.path.join(export_path, filename)
    
    # Write response to JSON file
    with open(file_path, 'w') as json_file:
        json.dump(response_data, json_file, indent=2)
    
    return response_data, file_path

# def verify_recaptcha(response_token):
#     """Verify the reCAPTCHA response token with Google's API."""
#     try:
#         data = {
#             'secret': app.config['RECAPTCHA_SECRET_KEY'],
#             'response': response_token
#         }
#         response = requests.post('https://www.google.com/recaptcha/api/siteverify', data=data)
#         result = response.json()
#         return result.get('success', False)
#     except Exception as e:
#         print(f"reCAPTCHA verification error: {str(e)}")
#         return False

# Add this decorator for rate limiting
def rate_limit(limit=5, per=300):  # 5 requests per 5 minutes
    def decorator(f):
        requests = {}
        @wraps(f)
        def wrapped(*args, **kwargs):
            now = datetime.now()
            ip = request.remote_addr
            
            # Clean old requests
            requests[ip] = [req_time for req_time in requests.get(ip, []) 
                          if (now - req_time).total_seconds() < per]
            
            # Check if limit exceeded
            if len(requests.get(ip, [])) >= limit:
                return jsonify({
                    'success': False,
                    'message': 'Too many requests. Please try again later.'
                }), 429
            
            # Add current request
            requests[ip] = requests.get(ip, []) + [now]
            
            return f(*args, **kwargs)
        return wrapped
    return decorator

@app.route('/form/<int:form_id>/submit', methods=['POST'])
@rate_limit(limit=5, per=300)  # 5 requests per 5 minutes
def submit_form(form_id):
    form = Form.query.get_or_404(form_id)
    
    # Check if form is closed
    if form.is_closed:
        return jsonify({
            'status': 'error',
            'message': 'This form is closed and no longer accepting responses.'
        }), 403
    
    # Get user_id and company_name from query parameters
    user_id = request.args.getlist('q')[0]  # First 'q' param = userId
    company_name = request.args.getlist('q')[1]  # Second 'q' param = companyName
    
    # Verify reCAPTCHA
    # if not verify_recaptcha(request.form.get('g-recaptcha-response')):
    #     return jsonify({
    #         'status': 'error',
    #         'message': 'reCAPTCHA verification failed. Please try again.'
    #     }), 400
    
    # Get UTM parameters and device type
    utm_params = extract_utm_parameters(request)
    device_type = detect_device_type(request.user_agent.string)
    
    # Create response object
    response = Response(
        form_id=form_id,
        company_id=form.company_id,
        user_id=user_id,                  
        company_name=company_name,        
        utm_source=utm_params.get('utm_source'),
        utm_medium=utm_params.get('utm_medium'),
        utm_campaign=utm_params.get('utm_campaign'),
        utm_content=utm_params.get('utm_content'),
        utm_term=utm_params.get('utm_term'),
        device_type=device_type,
        has_consent=True,
        status="pending" if form.merged_url else "success"
    )

    # Get geolocation data
    geolocation_data = request.form.get('geolocation')
    if geolocation_data:
        try:
            geo_data = json.loads(geolocation_data)
            geolocation = Geolocation(
                response=response,
                latitude=geo_data.get('latitude'),
                longitude=geo_data.get('longitude'),
                city=geo_data.get('city'),
                region=geo_data.get('region'),
                country=geo_data.get('country'),
                ip_address=request.remote_addr
            )
            db.session.add(geolocation)
        except json.JSONDecodeError:
            print("Error parsing geolocation data")

    # Process form answers and calculate quiz score if it's a quiz
    total_score = 0
    max_score = 0
    
    for question in form.questions:
        answer_text = request.form.get(f'question_{question.id}')
        if answer_text:
            answer = Answer(
                response=response,
                question_id=question.id,
                answer_text=answer_text
            )
            db.session.add(answer)
            
            # Calculate quiz score if this is a quiz question
            if form.is_quiz and question.is_quiz_question:
                max_score += question.points
                try:
                    correct_answers = json.loads(question.correct_answer) if question.correct_answer else []
                    if not isinstance(correct_answers, list):
                        correct_answers = [correct_answers]
                    
                    # For checkbox questions, check if all selected answers are correct
                    if question.question_type == 'checkbox':
                        user_answers = json.loads(answer_text) if answer_text.startswith('[') else [answer_text]
                        if all(ans in correct_answers for ans in user_answers):
                            total_score += question.points
                    # For other question types, check if the answer matches
                    elif answer_text in correct_answers:
                        total_score += question.points
                except (json.JSONDecodeError, TypeError):
                    # If there's an error parsing the correct answer, skip scoring this question
                    pass
    
    # Set quiz score and passed status if it's a quiz
    if form.is_quiz:
        response.score = total_score
        response.max_score = max_score
        if max_score > 0:
            score_percentage = (total_score / max_score) * 100
            response.passed = score_percentage >= form.passing_score
        else:
            response.passed = False

    db.session.add(response)
    db.session.commit()

    # Return success response
    # return jsonify({
    #     'status': 'success',
    #     # 'redirect_url': url_for('form_submitted', form_id=form_id, response_id=response.id)
    #     'redirect_url': form.merged_url if form.merged_url else url_for('form_submitted', form_id=form_id, response_id=response.id)
    # })
    # redirect_url = form.merged_url if form.merged_url else url_for('form_submitted', form_id=form_id, response_id=response.id)
    # return redirect(redirect_url)
    from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
    if form.merged_url:
       parsed_url = urlparse(form.merged_url)
       query_params = parse_qs(parsed_url.query)
       query_params['formClone_RespondeId'] = [str(response.id)]
       new_query = urlencode(query_params, doseq=True)
       redirect_url = urlunparse(parsed_url._replace(query=new_query))
    else:
      redirect_url = url_for('form_submitted', form_id=form_id, response_id=response.id)
    return redirect(redirect_url)


# Add a success page route
@app.route('/form/<int:form_id>/submitted')
def form_submitted(form_id):
    form = Form.query.get_or_404(form_id)
    
    # If response_id is in the URL, fetch it for displaying quiz results
    response_id = request.args.get('response_id', type=int)
    response = None
    
    if response_id:
        response = Response.query.get(response_id)
    
    return render_template('form_submitted.html', form=form, response=response, now=datetime.now())

@app.route('/form/<int:form_id>/responses')
@login_required
def view_responses(form_id):
    form = Form.query.get_or_404(form_id)
    if form.user_id != current_user.id:
        flash('You do not have permission to view these responses')
        return redirect(url_for('dashboard'))
    
    responses = Response.query.filter_by(form_id=form_id).all()
    
    # Get geolocation data for each response
    response_data = []
    for response in responses:
        geo = Geolocation.query.filter_by(response_id=response.id).first()
        response_data.append({
            'response': response,
            'geolocation': geo
        })
    
    return render_template('view_responses.html', form=form, response_data=response_data)

@app.route('/form/<int:form_id>/responses/export-json')
@login_required
def export_responses_json(form_id):
    form = Form.query.get_or_404(form_id)
    if form.user_id != current_user.id:
        flash('You do not have permission to export these responses')
        return redirect(url_for('dashboard'))
    
    responses = Response.query.filter_by(form_id=form_id).all()
    
    # Create a list to hold all responses
    all_responses = []
    
    for response in responses:
        # Use the helper function to export each response
        response_data, _ = export_response_to_json(response, form)
        all_responses.append(response_data)
    
    # Create export directory if it doesn't exist
    export_path = os.path.join('exports', 'survey_responses')
    os.makedirs(export_path, exist_ok=True)
    
    # Create filename with form ID and timestamp
    timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    filename = f"all_responses_form_{form_id}_{timestamp}.json"
    file_path = os.path.join(export_path, filename)
    
    # Write all responses to JSON file
    with open(file_path, 'w') as json_file:
        json.dump(all_responses, json_file, indent=2)
    
    # Return the file as a download
    return send_file(file_path, as_attachment=True, download_name=filename)

@app.route('/form/<int:form_id>/delete', methods=['POST'])
@login_required
def delete_form(form_id):
    try:
        # Get the form and verify ownership
        form = Form.query.get_or_404(form_id)
        if form.user_id != current_user.id:
            flash('You do not have permission to delete this form', 'danger')
            return redirect(url_for('dashboard'))
        
        # Check for _method parameter to confirm deletion intent
        _method = request.form.get('_method')
        if _method != 'DELETE':
            flash('Invalid deletion request', 'danger')
            return redirect(url_for('dashboard'))
        
        # Delete associated files
        if hasattr(form, 'pdf_upload') and form.pdf_upload:
            pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], form.pdf_upload.filename)
            if os.path.exists(pdf_path):
                os.remove(pdf_path)
            db.session.delete(form.pdf_upload)
        
        # Delete exported response files
        export_path = os.path.join('exports', 'survey_responses')
        if os.path.exists(export_path):
            for file in os.listdir(export_path):
                if file.startswith(f'response_{form.id}_'):
                    os.remove(os.path.join(export_path, file))
        
        # Delete the form (this will cascade delete questions, responses, etc.)
        db.session.delete(form)
        db.session.commit()
        
        flash('Form deleted successfully', 'success')
        return redirect(url_for('dashboard'))
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting form: {str(e)}', 'danger')
        return redirect(url_for('dashboard'))

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() == 'pdf'

def extract_questions_from_pdf(pdf_path):
    questions = []
    try:
        with open(pdf_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            for page in reader.pages:
                text = page.extract_text()
                lines = text.split('\n')
                i = 0
                while i < len(lines):
                    line = lines[i].strip()
                    next_line = lines[i + 1].strip() if i + 1 < len(lines) else ""
                    
                    # Skip empty lines
                    if not line:
                        i += 1
                        continue
                    
                    # Function to clean text - only keep alphabets and spaces
                    def clean_text(text):
                        # Keep only alphabets and spaces
                        text = ''.join(c for c in text if c.isalpha() or c == ' ')
                        # Remove extra spaces
                        text = ' '.join(text.split())
                        return text
                    
                    # Check for multiple choice questions
                    if any(option in line for option in ['(a)', '(b)', '(c)', '(d)', '(A)', '(B)', '(C)', '(D)']):
                        question_text = clean_text(line)
                        options = []
                        while i + 1 < len(lines) and any(option in lines[i + 1] for option in ['(a)', '(b)', '(c)', '(d)', '(A)', '(B)', '(C)', '(D)']):
                            i += 1
                            option_text = lines[i].strip()
                            # Remove option markers and clean text
                            option_text = option_text.split(')', 1)[1].strip() if ')' in option_text else option_text
                            option_text = clean_text(option_text)
                            options.append(option_text)
                        
                        questions.append({
                            'text': question_text,
                            'type': 'multiple_choice',
                            'options': options,
                            'required': True
                        })
                    
                    # Check for checkbox questions
                    elif any(checkbox in line for checkbox in ['[ ]', '[  ]', '□']):
                        question_text = clean_text(line)
                        options = []
                        while i + 1 < len(lines) and any(checkbox in lines[i + 1] for checkbox in ['[ ]', '[  ]', '□']):
                            i += 1
                            option_text = lines[i].strip()
                            # Remove checkbox markers and clean text
                            option_text = option_text.replace('[ ]', '').replace('[  ]', '').replace('□', '').strip()
                            option_text = clean_text(option_text)
                            options.append(option_text)
                        
                        questions.append({
                            'text': question_text,
                            'type': 'checkbox',
                            'options': options,
                            'required': True
                        })
                    
                    # Check for text input questions (with underline)
                    elif '_' in line or '___' in line:
                        # Extract the question part before the underline
                        question_text = line.split('_')[0].strip()
                        question_text = clean_text(question_text)
                        if question_text.endswith('?'):
                            questions.append({
                                'text': question_text,
                                'type': 'text',
                                'required': True
                            })
                    
                    # Check for regular questions
                    elif line.endswith('?'):
                        # Check if it's a required question (marked with *)
                        required = '*' in line
                        question_text = line.replace('*', '').strip()
                        question_text = clean_text(question_text)
                        
                        # Check if next line has options
                        if i + 1 < len(lines) and any(option in lines[i + 1] for option in ['(a)', '(b)', '(c)', '(d)', '(A)', '(B)', '(C)', '(D)']):
                            options = []
                            while i + 1 < len(lines) and any(option in lines[i + 1] for option in ['(a)', '(b)', '(c)', '(d)', '(A)', '(B)', '(C)', '(D)']):
                                i += 1
                                option_text = lines[i].strip()
                                # Remove option markers and clean text
                                option_text = option_text.split(')', 1)[1].strip() if ')' in option_text else option_text
                                option_text = clean_text(option_text)
                                options.append(option_text)
                            
                            questions.append({
                                'text': question_text,
                                'type': 'multiple_choice',
                                'options': options,
                                'required': required
                            })
                        else:
                            questions.append({
                                'text': question_text,
                                'type': 'text',
                                'required': required
                            })
                    
                    i += 1
                    
    except Exception as e:
        flash(f'Error processing PDF: {str(e)}')
    return questions

@app.route('/form/<int:form_id>/update', methods=['POST'])
@login_required
def update_form(form_id):
    form = Form.query.get_or_404(form_id)
    if form.user_id != current_user.id:
        return jsonify({'error':'Unauthorized'}), 403

    data = request.get_json(force=True)
    if 'questions' not in data:
        return jsonify({'error':'Invalid payload'}), 400

    try:
        # Debug incoming data
        print(f"Received form update data: {json.dumps(data, indent=2)}")
        
        # Update privacy consent requirement if provided
        if 'requires_consent' in data:
            form.requires_consent = data['requires_consent']
        
        # Update quiz settings if provided
        if 'is_quiz' in data:
            form.is_quiz = data['is_quiz']
        if 'passing_score' in data:
            form.passing_score = int(data['passing_score'])
        if 'show_score' in data:
            form.show_score = data['show_score']
        
        # Begin transaction
        # Step 1: Delete all old subquestions (this will cascade to subquestion answers)
        subquestions = SubQuestion.query.join(Question).filter(Question.form_id == form_id).all()
        for sq in subquestions:
            db.session.delete(sq)
        
        # Step 2: Delete old questions (which will cascade to their answers)
        questions = Question.query.filter_by(form_id=form_id).all()
        for q in questions:
            db.session.delete(q)
        
        db.session.commit()

        # Step 3: Re-create questions with their subquestions
        for idx, q_data in enumerate(data['questions']):
            question_type = q_data['question_type']
            
            # Create main question
            question = Question(
                form_id=form_id,
                question_text=q_data['question_text'],
                question_type=question_type,
                required=q_data.get('required', False),
                order=idx,
                # Add quiz-related fields
                is_quiz_question=q_data.get('is_quiz_question', False),
                correct_answer=q_data.get('correct_answer', None),
                points=q_data.get('points', 0),
                feedback=q_data.get('feedback', None)
            )
            
            # Process options for choice-based questions
            if question_type in ['radio', 'multiple_choice', 'checkbox']:
                options_data = q_data.get('options', [])
                
                # If options is a string, try to parse it
                if isinstance(options_data, str):
                    try:
                        options_data = json.loads(options_data)
                        print(f"Parsed options: {options_data}")
                    except Exception as e:
                        print(f"Error parsing options JSON: {str(e)}")
                        options_data = []
                
                # Make sure options_data is now a list
                if not isinstance(options_data, list):
                    print(f"Warning: Expected options to be a list, got {type(options_data)}. Converting to empty list.")
                    options_data = []
                
                # Save options as JSON - this stores all the option data including media properties
                question.options = json.dumps(options_data)
                print(f"Saving options for question {idx+1}: {question.options}")
                
                # Add question to session so we can get its ID for subquestions
                db.session.add(question)
                db.session.flush()  # This assigns the ID but doesn't commit
                
                # Process subquestions if they exist
                for option_idx, option_data in enumerate(options_data):
                    # Check if this is a simple option string or an object with subquestions
                    if isinstance(option_data, dict):
                        option_text = option_data.get('text', '')
                        subquestions_data = option_data.get('subquestions', [])
                        
                        # Process each subquestion for this option
                        for subq_idx, subq_data in enumerate(subquestions_data):
                            sub_q = SubQuestion(
                                question_id=question.id,
                                parent_option=option_text,
                                question_text=subq_data.get('text', ''),
                                question_type=subq_data.get('type', 'text'),
                                required=subq_data.get('required', False),
                                order=subq_idx,
                                nesting_level=1
                            )
                            
                            # Handle options for subquestions
                            if 'options' in subq_data:
                                sub_options = subq_data['options']
                                if isinstance(sub_options, list):
                                    sub_q.options = json.dumps(sub_options)
                                    
                                    # Process nested subquestions (level 2)
                                    for nested_idx, nested_option in enumerate(sub_options):
                                        if isinstance(nested_option, dict) and 'subquestions' in nested_option:
                                            for nested_subq_idx, nested_subq in enumerate(nested_option['subquestions']):
                                                nested_q = SubQuestion(
                                                    question_id=question.id,
                                                    parent_option=f"{option_text}|{nested_option.get('text', '')}",
                                                    question_text=nested_subq.get('text', ''),
                                                    question_type=nested_subq.get('type', 'text'),
                                                    required=nested_subq.get('required', False),
                                                    order=nested_subq_idx,
                                                    nesting_level=2
                                                )
                                                
                                                if 'options' in nested_subq:
                                                    nested_q.options = json.dumps(nested_subq['options'])
                                                
                                                db.session.add(nested_q)
                            
                            db.session.add(sub_q)
            else:
                # For non-choice questions, just save without options
                db.session.add(question)
        
        # Commit all changes
        db.session.commit()
        print("Form updated successfully")
        return jsonify({'message':'Form updated successfully', 'status': 'success'}), 200
    
    except Exception as e:
        db.session.rollback()
        print(f"Error updating form: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/postback/dashboard')
@login_required
def postback_dashboard():
    # Get all forms for this user
    forms = Form.query.filter_by(user_id=current_user.id).all()
    
    # Get tracking IDs for these forms
    form_ids = [form.id for form in forms]
    trackings = PostbackTracking.query.filter(PostbackTracking.form_id.in_(form_ids)).all()
    
    # Get tracking IDs
    tracking_ids = [t.tracking_id for t in trackings]
    
    # Get logs for these tracking IDs
    logs = PostbackLog.query.filter(PostbackLog.tracking_id.in_(tracking_ids)).order_by(PostbackLog.timestamp.desc()).limit(100).all()
    
    # Group by form
    form_postbacks = {}
    for form in forms:
        form_tracking = next((t for t in trackings if t.form_id == form.id), None)
        if form_tracking:
            form_logs = [log for log in logs if log.tracking_id == form_tracking.tracking_id]
            postback_url = f"http://pepper-ads.com/postback?tracking_id={form_tracking.tracking_id}&user_id={form.user_id}"
            
            form_postbacks[form.id] = {
                'form': form,
                'tracking': form_tracking,
                'logs': form_logs,
                'postback_url': postback_url
            }
    
    return render_template('postback_dashboard.html', form_postbacks=form_postbacks)

@app.route('/postback', methods=['GET', 'POST'])
def receive_postback():
    # Get parameters from either GET or POST
    if request.method == 'GET':
        params = request.args.to_dict()
    else:
        params = request.form.to_dict()
    
    # Extract key parameters
    tracking_id = params.get('tracking_id')
    transaction_id = params.get('transaction_id')
    username = params.get('username')
    user_id = params.get('user_id')
    status = params.get('status')
    payout = params.get('payout')
    
    if not tracking_id:
        return jsonify({'status': 'error', 'message': 'Missing tracking_id'}), 400
    
    # Try to convert payout to float if present
    if payout:
        try:
            payout = float(payout)
        except ValueError:
            payout = None
    
    # Find the tracking record
    tracking = PostbackTracking.query.filter_by(tracking_id=tracking_id).first()
    
    if tracking:
        # Increment transaction count
        tracking.transaction_count += 1
        tracking.last_updated = datetime.utcnow()
        
        # Create log entry
        log = PostbackLog(
            tracking_id=tracking_id,
            transaction_id=transaction_id,
            username=username,
            user_id=user_id,
            status=status,
            payout=payout,
            response_json=json.dumps(params),
            ip_address=request.remote_addr
        )
        
        db.session.add(log)
        db.session.commit()
        
        # Save to JSON file
        save_postback_to_json({
            'tracking_id': tracking_id,
            'transaction_id': transaction_id,
            'username': username,
            'user_id': user_id,
            'status': status,
            'payout': payout,
            'all_params': params,
            'ip_address': request.remote_addr
        })
        
        return jsonify({
            'status': 'success',
            'message': 'Postback received',
            'tracking_id': tracking_id
        })
    else:
        return jsonify({'status': 'error', 'message': 'Invalid tracking_id'}), 404

@app.route('/form/<int:form_id>/embed')
def embed_form(form_id):
    """Route for displaying a form in an embedded iframe context"""
    form = Form.query.get_or_404(form_id)
    
    # Get all subquestions for this form
    subquestions = SubQuestion.query.join(Question).filter(Question.form_id == form_id).all()

    # Process each question to handle nested structures
    for question in form.questions:
        if question.question_type in ['radio', 'multiple_choice']:
            try:
                # Parse options with full nested structure
                question.nested_options = json.loads(question.options or '[]')
                
                # If options is a plain array, convert to nested format
                if question.nested_options and isinstance(question.nested_options[0], str):
                    question.nested_options = [{"text": opt, "subquestions": []} for opt in question.nested_options]
            except (json.JSONDecodeError, TypeError, IndexError):
                # Fallback for legacy data format
                try:
                    raw_options = question.get_options()
                    # Convert simple options to the nested format
                    question.nested_options = [
                        {"text": opt, "subquestions": []} 
                        for opt in raw_options if opt
                    ]
                except Exception:
                    # Last resort fallback
                    question.nested_options = []

    # Sort questions by order
    form.questions.sort(key=lambda q: q.order)
    
    # Check if this is an embedded view (like Google Forms' embedded=true parameter)
    is_embedded = request.args.get('embedded') == 'true'
    
    # Use the dedicated embed template instead of view_form.html
    return render_template('embed_form.html', form=form, subquestions=subquestions, 
                          is_embedded=is_embedded, is_closed=form.is_closed)

@app.route('/form/<int:form_id>/share')
@login_required
def share_form(form_id):
    form = Form.query.get_or_404(form_id)
    if form.user_id != current_user.id:
        flash('You do not have permission to share this form')
        return redirect(url_for('dashboard'))
    
    # Getting the base URL with protocol (http/https)
    if request.headers.get('X-Forwarded-Proto'):
        proto = request.headers.get('X-Forwarded-Proto')
    else:
        proto = 'https' if request.is_secure else 'http'
    
    host = request.host
    base_url = f"{proto}://{host}"
    
    # Use pepper-ads.com domain for production
    production_url = "http://pepper-ads.com"
    
    # Create the base share URL with form and user parameters
    base_share_url = f"{production_url}/?form_id={form.id}&user_id={form.user_id}"
    
    # Generate postback URL for this form
    postback_url = generate_postback_url(form.id, form.user_id)
    
    # Detect current device type from request
    current_device = detect_device_type(request.user_agent.string)
    
    # Create additional share URLs with UTM parameters for different platforms
    # Now including device parameter
    share_urls = {
        'default': f"{base_share_url}&utm_source=default&utm_medium=referral&utm_campaign=form_share&device={current_device}",
        'facebook': f"{base_share_url}&utm_source=facebook&utm_medium=social&utm_campaign=form_share&device={current_device}",
        'twitter': f"{base_share_url}&utm_source=twitter&utm_medium=social&utm_campaign=form_share&device={current_device}",
        'linkedin': f"{base_share_url}&utm_source=linkedin&utm_medium=social&utm_campaign=april_launch&device={current_device}",
        'email': f"{base_share_url}&utm_source=email&utm_medium=email&utm_campaign=form_share&device={current_device}"
    }
    
    # You can also create a generic UTM share URL if needed
    utm_share_url = f"{base_share_url}&utm_source=other&utm_medium=referral&utm_campaign=form_share&device={current_device}"
    
    # Create embed URLs for iframes
    embed_url = f"{base_url}/form/{form.id}/embed"
    
    # Generate iframe HTML code
    iframe_code = f'<iframe src="{embed_url}" width="100%" height="600" frameborder="0" marginheight="0" marginwidth="0">Loading…</iframe>'
    
    return render_template('share_form.html', form=form, 
                          base_url=base_url,
                          production_url=production_url,
                          share_url=f"{base_share_url}&device={current_device}", 
                          share_urls=share_urls,
                          utm_share_url=utm_share_url,
                          current_device=current_device,
                          postback_url=postback_url,
                          embed_url=embed_url,
                          iframe_code=iframe_code)  # Add embed URL and iframe code to template

@app.route('/upload_pdf', methods=['GET', 'POST'])
@login_required
def upload_pdf():
    if request.method == 'POST':
        if 'pdf' not in request.files:
            flash('No file part')
            return redirect(request.url)
        
        file = request.files['pdf']
        if file.filename == '':
            flash('No selected file')
            return redirect(request.url)
        
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            unique_filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
            file.save(file_path)
            
            # Create PDF upload record
            pdf_upload = PDFUpload(
                filename=unique_filename,
                original_filename=filename,
                user_id=current_user.id,
                form_id=None  # Will be updated after form creation
            )
            db.session.add(pdf_upload)
            db.session.commit()
            
            # Extract questions and create form
            questions = extract_questions_from_pdf(file_path)
            if questions:
                form = Form(
                    title=f"Form from {filename}",
                    description="Automatically generated from PDF",
                    user_id=current_user.id,
                    company_id=session.get('referral_company_id')
                )
                db.session.add(form)
                db.session.commit()
                
                # Update PDF upload with form ID
                pdf_upload.form_id = form.id
                
                # Add questions to form
                for i, q in enumerate(questions):
                    question = Question(
                        form_id=form.id,
                        question_text=q['text'],
                        question_type=q['type'],
                        required=q['required'],
                        order=i
                    )
                    if 'options' in q:
                        question.set_options(q['options'])
                    db.session.add(question)
                
                db.session.commit()
                
                # Clear referral from session after form creation
                session.pop('referral_company_id', None)
                
                flash('Form generated successfully!')
                return redirect(url_for('edit_form', form_id=form.id))
            else:
                flash('No questions found in the PDF')
                return redirect(url_for('upload_pdf'))
    
    return render_template('upload_pdf.html')

def parse_mindmap_to_form(mindmap_text):
    form_data = {
        "title": "",
        "sections": []
    }
    
    current_section = None
    current_field = None
    
    lines = mindmap_text.split('\n')
    for line in lines:
        # Skip empty lines
        if not line.strip():
            continue
            
        # Count indentation level (number of spaces at start)
        indent_level = len(line) - len(line.lstrip())
        
        # Root level - Form title
        if indent_level == 0:
            form_data["title"] = line.strip()
            
        # First level - Sections
        elif indent_level == 2:  # Two spaces for sections
            # Remove "Section X:" prefix if present
            section_name = line.strip()
            if ":" in section_name:
                section_name = section_name.split(":", 1)[1].strip()
            
            current_section = {
                "name": section_name,
                "fields": []
            }
            form_data["sections"].append(current_section)
            
        # Second level - Fields
        elif indent_level == 4:  # Four spaces for fields
            field_parts = line.strip().split('|')
            field_label = field_parts[0].strip()
            field_type = "text"  # default type
            
            if len(field_parts) > 1:
                type_spec = field_parts[1].strip().lower()
                if type_spec in ['text', 'dropdown', 'checkbox', 'radio', 'email']:
                    field_type = type_spec
            
            current_field = {
                "label": field_label,
                "type": field_type,
                "options": []
            }
            current_section["fields"].append(current_field)
            
        # Third level - Options (for dropdown/checkbox/radio)
        elif indent_level == 6 and current_field:  # Six spaces for options
            if current_field["type"] in ['dropdown', 'checkbox', 'radio']:
                current_field["options"].append(line.strip())
    
    return form_data

@app.route('/upload_mindmap', methods=['GET', 'POST'])
@login_required
def upload_mindmap():
    if request.method == 'POST':
        mindmap_text = request.form.get('mindmap_text')
        if not mindmap_text:
            flash('No mindmap text provided')
            return redirect(request.url)
            
        try:
            form_data = parse_mindmap_to_form(mindmap_text)
            
            form = Form(
                title=form_data["title"],
                description="Generated from mindmap",
                user_id=current_user.id,
                company_id=session.get('referral_company_id')
            )
            db.session.add(form)
            db.session.commit()
            
            order = 0
            for section in form_data["sections"]:
                for field in section["fields"]:
                    type_mapping = {
                        'text': 'text',
                        'email': 'email',
                        'dropdown': 'multiple_choice',
                        'checkbox': 'checkbox',
                        'radio': 'radio'
                    }
                    
                    question_type = type_mapping.get(field["type"], 'text')
                    
                    question = Question(
                        form_id=form.id,
                        question_text=field["label"],
                        question_type=question_type,
                        required=True,
                        order=order
                    )
                    
                    if question_type in ['multiple_choice', 'checkbox', 'radio'] and field["options"]:
                        question.set_options(field["options"])
                    
                    db.session.add(question)
                    order += 1
            
            db.session.commit()
            
            # Clear referral from session after form creation
            session.pop('referral_company_id', None)
            
            flash('Form generated successfully from mindmap!')
            return redirect(url_for('edit_form', form_id=form.id))
            
        except Exception as e:
            flash(f'Error processing mindmap: {str(e)}')
            return redirect(url_for('upload_mindmap'))
    
    return render_template('upload_mindmap.html')

@app.route('/manage_companies', methods=['GET', 'POST'])
@login_required
def manage_companies():
    if request.method == 'POST':
        name = request.form.get('name')
        referral_code = request.form.get('referral_code')
        
        if not name or not referral_code:
            flash('Company name and referral code are required')
            return redirect(url_for('manage_companies'))
            
        company = Company(name=name, referral_code=referral_code)
        db.session.add(company)
        db.session.commit()
        flash('Company added successfully')
        return redirect(url_for('manage_companies'))
        
    companies = Company.query.all()
    return render_template('manage_companies.html', companies=companies)

@app.route('/referral/<referral_code>')
def handle_referral(referral_code):
    company = Company.query.filter_by(referral_code=referral_code).first()
    if not company:
        flash('Invalid referral link')
        return redirect(url_for('index'))
        
    # Store company_id in session for form creation
    session['referral_company_id'] = company.id
    return redirect(url_for('create_form'))

def initialize_templates():
    """Initialize some default templates if none exist"""
    if FormTemplate.query.count() == 0:
        print("Creating predefined templates...")
        default_templates = [
            {
                'title': 'Contact Information',
                'description': 'Collect contact information from your customers or clients',
                'category': 'contact',
                'preview_image': 'https://ssl.gstatic.com/docs/templates/thumbnails/10erh7nUxj1plOplVrZuDLCTQn0VYdVrFiWMsImLrDE0_400.png',
                'questions': [
                    {
                        'question_text': 'Full Name',
                        'question_type': 'text',
                        'required': True
                    },
                    {
                        'question_text': 'Email',
                        'question_type': 'email',
                        'required': True
                    },
                    {
                        'question_text': 'Phone Number',
                        'question_type': 'tel',
                        'required': False
                    },
                    {
                        'question_text': 'Address',
                        'question_type': 'text',
                        'required': False
                    },
                    {
                        'question_text': 'How would you prefer to be contacted?',
                        'question_type': 'radio',
                        'options': ['Email', 'Phone', 'Text Message'],
                        'required': True
                    }
                ]
            },
            {
                'title': 'Event Registration',
                'description': 'Register attendees for your upcoming event',
                'category': 'event',
                'preview_image': 'https://ssl.gstatic.com/docs/templates/thumbnails/1XykI9graIiCpCfrL-tDY7hBfNRoamwF_K3NpmJugW10_400.png',
                'questions': [
                    {
                        'question_text': 'Full Name',
                        'question_type': 'text',
                        'required': True
                    },
                    {
                        'question_text': 'Email Address',
                        'question_type': 'email',
                        'required': True
                    },
                    {
                        'question_text': 'Phone Number',
                        'question_type': 'tel',
                        'required': True
                    },
                    {
                        'question_text': 'Which sessions will you attend?',
                        'question_type': 'checkbox',
                        'options': ['Morning Workshop', 'Afternoon Panel', 'Evening Networking', 'All Sessions'],
                        'required': True
                    },
                    {
                        'question_text': 'Dietary Restrictions',
                        'question_type': 'checkbox',
                        'options': ['Vegetarian', 'Vegan', 'Gluten-Free', 'Nut Allergy', 'None'],
                        'required': False
                    }
                ]
            },
            {
                'title': 'Customer Feedback',
                'description': 'Collect feedback about your products or services',
                'category': 'feedback',
                'preview_image': 'https://ssl.gstatic.com/docs/templates/thumbnails/10Z7d4HPigN_VUiFf7tsP5x6DO-NmZ1CTkHEECH9JrE4_400.png',
                'questions': [
                    {
                        'question_text': 'How satisfied are you with our service?',
                        'question_type': 'radio',
                        'options': ['Very Satisfied', 'Satisfied', 'Neutral', 'Dissatisfied', 'Very Dissatisfied'],
                        'required': True
                    },
                    {
                        'question_text': 'What aspects did you like most?',
                        'question_type': 'checkbox',
                        'options': ['Customer Support', 'Product Quality', 'Pricing', 'User Experience', 'Delivery Speed'],
                        'required': True
                    },
                    {
                        'question_text': 'How likely are you to recommend us to others?',
                        'question_type': 'radio',
                        'options': ['Very Likely', 'Likely', 'Neutral', 'Unlikely', 'Very Unlikely'],
                        'required': True
                    },
                    {
                        'question_text': 'Additional comments or suggestions',
                        'question_type': 'text',
                        'required': False
                    }
                ]
            },
            {
                'title': 'Job Application',
                'description': 'Collect information from job applicants',
                'category': 'application',
                'preview_image': 'https://ssl.gstatic.com/docs/templates/thumbnails/1dnc-XoL33BwJgNZMLUZ5_Hj3F1z_AEYeNTcIWRR-QPI_400.png',
                'questions': [
                    {
                        'question_text': 'Full Name',
                        'question_type': 'text',
                        'required': True
                    },
                    {
                        'question_text': 'Email Address',
                        'question_type': 'email',
                        'required': True
                    },
                    {
                        'question_text': 'Phone Number',
                        'question_type': 'tel',
                        'required': True
                    },
                    {
                        'question_text': 'Position Applying For',
                        'question_type': 'text',
                        'required': True
                    },
                    {
                        'question_text': 'Years of Experience',
                        'question_type': 'radio',
                        'options': ['0-1 years', '1-3 years', '3-5 years', '5+ years'],
                        'required': True
                    },
                    {
                        'question_text': 'Resume/CV',
                        'question_type': 'file',
                        'required': True
                    },
                    {
                        'question_text': 'Cover Letter',
                        'question_type': 'text',
                        'required': False
                    }
                ]
            },
            {
                'title': 'Product Order Form',
                'description': 'Accept orders for your products',
                'category': 'order',
                'preview_image': 'https://ssl.gstatic.com/docs/templates/thumbnails/1XwQvBuou2HL_IGy4Nx-rFnGRk_iJ7JiRs5Y8EwNKbkI_400.png',
                'questions': [
                    {
                        'question_text': 'Customer Name',
                        'question_type': 'text',
                        'required': True
                    },
                    {
                        'question_text': 'Email Address',
                        'question_type': 'email',
                        'required': True
                    },
                    {
                        'question_text': 'Shipping Address',
                        'question_type': 'text',
                        'required': True
                    },
                    {
                        'question_text': 'Product Selection',
                        'question_type': 'radio',
                        'options': ['Product A - $19.99', 'Product B - $29.99', 'Product C - $39.99', 'Bundle Pack - $79.99'],
                        'required': True
                    },
                    {
                        'question_text': 'Quantity',
                        'question_type': 'number',
                        'required': True
                    },
                    {
                        'question_text': 'Payment Method',
                        'question_type': 'radio',
                        'options': ['Credit Card', 'PayPal', 'Bank Transfer'],
                        'required': True
                    }
                ]
            },
            {
                'title': 'RSVP Form',
                'description': 'Collect RSVPs for your event',
                'category': 'event',
                'preview_image': 'https://ssl.gstatic.com/docs/templates/thumbnails/1uiBg3yjY-S8_LHPLNcPE4pU17YvBM-tSrfKQgXIAQ5A_400.png',
                'questions': [
                    {
                        'question_text': 'Your Name',
                        'question_type': 'text',
                        'required': True
                    },
                    {
                        'question_text': 'Email Address',
                        'question_type': 'email',
                        'required': True
                    },
                    {
                        'question_text': 'Will you attend?',
                        'question_type': 'radio',
                        'options': ['Yes', 'No', 'Maybe'],
                        'required': True
                    },
                    {
                        'question_text': 'Number of Guests',
                        'question_type': 'number',
                        'required': True
                    },
                    {
                        'question_text': 'Any dietary restrictions?',
                        'question_type': 'text',
                        'required': False
                    }
                ]
            }
        ]

        for template_data in default_templates:
            # Create a copy for database storage
            template_questions = []
            
            # Process each question to ensure options are properly formatted as JSON strings
            for question in template_data['questions']:
                question_copy = question.copy()  # Make a copy to avoid modifying original
                
                # Convert options list to JSON string if it exists
                if 'options' in question_copy and isinstance(question_copy['options'], list):
                    question_copy['options'] = json.dumps(question_copy['options'])
                
                template_questions.append(question_copy)
            
            # Create template
            template = FormTemplate(
                title=template_data['title'],
                description=template_data['description'],
                category=template_data['category'],
                preview_image=template_data['preview_image'],
                is_public=True
            )
            
            # Store questions with JSON string options
            template.questions = json.dumps(template_questions)
            
            # Create template_data structure with questions (keeping options as lists) and empty subquestions
            complete_data = {
                'questions': template_data['questions'],  # Original questions with options as lists
                'subquestions': []
            }
            
            # Store the complete template data
            template.template_data = json.dumps(complete_data)
            
            db.session.add(template)
        
        db.session.commit()
        print("Created predefined templates successfully!")

@app.route('/templates')
def template_gallery():
    categories = db.session.query(FormTemplate.category).distinct().all()
    categories = [cat[0] for cat in categories if cat[0]]
    
    selected_category = request.args.get('category')
    search_query = request.args.get('search', '')
    
    query = FormTemplate.query.filter_by(is_public=True)
    
    if selected_category:
        query = query.filter_by(category=selected_category)
    
    if search_query:
        query = query.filter(
            (FormTemplate.title.ilike(f'%{search_query}%')) |
            (FormTemplate.description.ilike(f'%{search_query}%'))
        )
    
    templates = query.order_by(FormTemplate.created_at.desc()).all()
    return render_template('template_gallery.html', 
                         templates=templates,
                         categories=categories,
                         selected_category=selected_category,
                         search_query=search_query)

@app.route('/template/<int:template_id>')
def view_template(template_id):
    template = FormTemplate.query.get_or_404(template_id)
    if not template.is_public and (not current_user.is_authenticated or template.user_id != current_user.id):
        flash('You do not have permission to view this template.', 'danger')
        return redirect(url_for('template_gallery'))
    
    return render_template('view_template.html', template=template)

@app.route('/template/<int:template_id>/use')
@login_required
def use_template(template_id):
    try:
        # Get the template
        template = FormTemplate.query.get_or_404(template_id)
        
        # Create a new form based on the template
        new_form = Form(
            title=template.title,
            description=template.description or "",
            user_id=current_user.id
        )
        db.session.add(new_form)
        db.session.flush()  # Get ID without committing
        
        # Get template data - with backwards compatibility
        template_data_str = template.get_template_data()
        template_data = json.loads(template_data_str)
        
        # If no template data structure, convert from old questions format
        if not template_data or 'questions' not in template_data:
            template_data = {
                'questions': template.get_questions(),
                'subquestions': []
            }
        
        # Create a mapping of original question IDs to new question IDs
        id_mapping = {}
        
        # Process questions first
        for q_idx, q_data in enumerate(template_data.get('questions', [])):
            # Convert options to JSON if it's a list
            options_data = q_data.get('options')
            if isinstance(options_data, list):
                options_json = json.dumps(options_data)
            else:
                options_json = options_data
            
            # Create new question
            new_question = Question(
                form_id=new_form.id,
                question_text=q_data.get('question_text', ''),
                question_type=q_data.get('question_type', 'text'),
                required=q_data.get('required', False),
                order=q_idx,
                options=options_json
            )
            db.session.add(new_question)
            db.session.flush()  # Get ID without committing
            
            # Store mapping of template question ID to new question ID
            original_id = q_data.get('id')
            if original_id:
                id_mapping[original_id] = new_question.id
        
        # Process subquestions if present in the template
        if 'subquestions' in template_data:
            for subq_data in template_data.get('subquestions', []):
                # Get the parent question ID from the mapping
                parent_id = id_mapping.get(subq_data.get('question_id'))
                if parent_id:
                    # Convert options to JSON if it's a list
                    sub_options_data = subq_data.get('options')
                    if isinstance(sub_options_data, list):
                        sub_options_json = json.dumps(sub_options_data)
                    else:
                        sub_options_json = sub_options_data
                    
                    new_subq = SubQuestion(
                        question_id=parent_id,
                        parent_option=subq_data.get('parent_option', ''),
                        question_text=subq_data.get('question_text', ''),
                        question_type=subq_data.get('question_type', 'text'),
                        required=subq_data.get('required', False),
                        order=subq_data.get('order', 0),
                        nesting_level=subq_data.get('nesting_level', 1),
                        options=sub_options_json
                    )
                    db.session.add(new_subq)
        
        # Commit the transaction
        db.session.commit()
        
        flash("Form created from template successfully!", "success")
        return redirect(url_for('edit_form', form_id=new_form.id))
    
    except Exception as e:
        db.session.rollback()
        flash(f"Error creating form from template: {str(e)}", "danger")
        return redirect(url_for('dashboard'))

@app.route('/template/upload', methods=['GET', 'POST'])
@login_required
def upload_template():
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        category = request.form.get('category')
        questions = request.form.get('questions')
        is_public = request.form.get('is_public') == 'on'
        
        try:
            questions_data = json.loads(questions)
        except:
            flash('Invalid questions data', 'danger')
            return redirect(url_for('upload_template'))
        
        template = FormTemplate(
            title=title,
            description=description,
            category=category,
            is_public=is_public,
            user_id=current_user.id
        )
        template.set_questions(questions_data)
        
        db.session.add(template)
        db.session.commit()
        
        flash('Template uploaded successfully!', 'success')
        return redirect(url_for('template_gallery'))
    
    return render_template('upload_template.html')

@app.route('/form/<int:form_id>/embed-demo')
@login_required
def form_embed_demo(form_id):
    """Demo page showing how to embed forms and handle form submission events"""
    form = Form.query.get_or_404(form_id)
    if form.user_id != current_user.id:
        flash('You do not have permission to access this form')
        return redirect(url_for('dashboard'))
    
    # Create embed URL
    if request.headers.get('X-Forwarded-Proto'):
        proto = request.headers.get('X-Forwarded-Proto')
    else:
        proto = 'https' if request.is_secure else 'http'
    
    host = request.host
    base_url = f"{proto}://{host}"
    
    # Generate embed URL and iframe code
    embed_url = f"{base_url}/form/{form.id}/embed"
    iframe_code = f'<iframe src="{embed_url}" width="100%" height="600" frameborder="0" marginheight="0" marginwidth="0">Loading…</iframe>'
    
    return render_template('form_embed_demo.html', 
                          form=form, 
                          embed_url=embed_url,
                          iframe_code=iframe_code)

@app.route('/form/<int:form_id>/toggle-status', methods=['POST'])
@login_required
def toggle_form_status(form_id):
    form = Form.query.get_or_404(form_id)
    if form.user_id != current_user.id:
        flash('You do not have permission to modify this form', 'danger')
        return redirect(url_for('dashboard'))
        
    # Toggle the is_closed status
    form.is_closed = not form.is_closed
    db.session.commit()
    
    status = "closed" if form.is_closed else "reopened"
    flash(f'Form has been {status} successfully', 'success')
    
    # Check if the request is from AJAX
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'status': 'success',
            'is_closed': form.is_closed,
            'message': f'Form has been {status} successfully'
        })
    
    # Redirect to the appropriate page based on referrer
    referrer = request.referrer
    if referrer and '/edit' in referrer:
        return redirect(url_for('edit_form', form_id=form_id))
    elif referrer and '/responses' in referrer:
        return redirect(url_for('view_responses', form_id=form_id))
    else:
        return redirect(url_for('dashboard'))

@app.route('/privacy-policy')
def privacy_policy():
    """Route for viewing the privacy policy"""
    return render_template('privacy_policy.html', now=datetime.now())

@app.route('/terms-and-conditions')
def terms_and_conditions():
    """Route for viewing the terms and conditions"""
    return render_template('terms_and_conditions.html', now=datetime.now())

@app.route('/form/<int:form_id>/privacy-policy')
def form_privacy_policy(form_id):
    """Route for viewing a specific form's privacy policy"""
    form = Form.query.get_or_404(form_id)
    return render_template('privacy_policy.html', form=form, now=datetime.now())

@app.route('/form/<int:form_id>/terms-and-conditions')
def form_terms_and_conditions(form_id):
    """Route for viewing a specific form's terms and conditions"""
    form = Form.query.get_or_404(form_id)
    return render_template('terms_and_conditions.html', form=form, now=datetime.now())

@app.route('/upload_media', methods=['POST'])
@login_required
def upload_media():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    # Get the description if provided
    description = request.form.get('description', '')
    
    # Check if file is an image or GIF
    allowed_extensions = {'png', 'jpg', 'jpeg', 'gif'}
    if '.' not in file.filename or file.filename.rsplit('.', 1)[1].lower() not in allowed_extensions:
        return jsonify({'error': 'Invalid file type. Only images and GIFs are allowed.'}), 400
    
    try:
        # Create a unique filename
        filename = secure_filename(file.filename)
        unique_filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
        
        # Create media directory if it doesn't exist
        media_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'media')
        os.makedirs(media_dir, exist_ok=True)
        
        # Save the file
        file_path = os.path.join(media_dir, unique_filename)
        file.save(file_path)
        
        # Return the URL for the uploaded file
        media_url = url_for('uploaded_file', filename=f'media/{unique_filename}')
        return jsonify({
            'success': True,
            'url': media_url,
            'filename': unique_filename,
            'description': description
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/business-insights')
@login_required
def business_insights():
    """Route for the business insights page"""
    # Get all forms with responses for the current user
    forms = Form.query.filter_by(user_id=current_user.id).all()
    return render_template('business_insights.html', forms=forms)

# Configure Google Generative AI
def configure_genai():
    """Configure Google Generative AI with proper error handling"""
    try:
        print("\n=== Configuring Google Generative AI ===")
        
        # Get API key from app config
        api_key = app.config.get('GOOGLE_API_KEY')
        
        if not api_key:
            print("Error: GOOGLE_API_KEY not found in app config")
            return False
            
        print(f"API Key found: {api_key[:5]}...{api_key[-5:]}")
        
        # Configure the API with specific settings
        try:
            google.generativeai.configure(
                api_key=api_key,
                transport='rest'  # Use REST transport explicitly
            )
            print("Successfully configured genai with API key")
        except Exception as e:
            print(f"Error configuring genai: {str(e)}")
            return False
        
        # Try to get a specific model directly
        try:
            print("\nAttempting to access Gemini Pro model...")
            model = google.generativeai.GenerativeModel('gemini-2.0-flash')
            
            # Test the model with a simple prompt
            test_response = model.generate_content("Hello")
            if test_response and hasattr(test_response, 'text'):
                print("Successfully tested model with simple prompt")
                return 'gemini-2.0-flash'
            else:
                print("Model test failed - no valid response")
                return False
                
        except Exception as e:
            print(f"Error accessing model: {str(e)}")
            print(f"Error type: {type(e)}")
            return False
            
    except Exception as e:
        print(f"Error in configure_genai: {str(e)}")
        print(f"Error type: {type(e)}")
        return False

def generate_insights_with_gemini(structured_data, form, insight_type):
    """Generate insights using Google's Gemini model"""
    try:
        print(f"\n=== Starting {insight_type} Generation ===")
        print(f"Form Title: {form.title}")
        print(f"Total Responses: {structured_data['form_info']['total_responses']}")
        
        # Configure the API with REST transport
        api_key = app.config['GOOGLE_API_KEY']
        if not api_key:
            raise ValueError("API key not found in app configuration")
            
        # Configure the Google client
        google.generativeai.configure(api_key=api_key)
        
        # Initialize the model
        model = google.generativeai.GenerativeModel('gemini-2.0-flash')
        print("Successfully configured Gemini 2.0 Flash model")
            
        # Prepare the prompt based on insight type
        if insight_type == 'product':
            prompt = f"""You are a business analyst. Analyze these form responses and generate detailed product insights.
            Form Information:
            - Title: {form.title}
            - Description: {form.description}
            - Total Responses: {structured_data['form_info']['total_responses']}
            
            Questions and Answers:
            {json.dumps(structured_data['question_answer_mapping'], indent=2)}
            
            Generate 5 detailed product insights with specific recommendations. For each insight:
            1. Provide a clear title
            2. Give a detailed analysis of the findings
            3. Include specific, actionable recommendations
            4. Add relevant metrics or statistics if possible
            
            Format your response as a JSON array with objects containing:
            - title: Brief insight title
            - description: Detailed explanation with data points
            - recommendations: Array of specific, actionable recommendations
            - metrics: Any relevant statistics or metrics
            
            Example format:
            [
                {{
                    "title": "Feature Popularity Analysis",
                    "description": "75% of users requested feature X, with 60% citing it as critical for their workflow",
                    "recommendations": [
                        "Implement feature X in Q3 2024",
                        "Create a beta testing program",
                        "Develop user documentation"
                    ],
                    "metrics": {{
                        "request_frequency": "75%",
                        "priority_level": "High"
                    }}
                }}
            ]
            
            Important: Your response must be a valid JSON array starting with [ and ending with ]. Do not include any markdown formatting or code block markers."""
            
        elif insight_type == 'market':
            prompt = f"""You are a market analyst. Analyze these form responses and identify detailed market segments.
            Form Information:
            - Title: {form.title}
            - Description: {form.description}
            - Total Responses: {structured_data['form_info']['total_responses']}
            
            Questions and Answers:
            {json.dumps(structured_data['question_answer_mapping'], indent=2)}
            
            Generate 5 detailed market segment insights with specific targeting strategies. For each segment:
            1. Identify key characteristics
            2. Analyze their needs and preferences
            3. Provide specific targeting recommendations
            4. Include market size or potential metrics
            
            Format your response as a JSON array with objects containing:
            - title: Segment name/description
            - description: Detailed analysis with demographic data
            - recommendations: Array of specific targeting strategies
            - metrics: Market size or potential metrics
            
            Example format:
            [
                {{
                    "title": "Enterprise Decision Makers",
                    "description": "Senior executives aged 35-50, primarily in tech and finance sectors",
                    "recommendations": [
                        "Target LinkedIn premium ads",
                        "Develop enterprise-specific features",
                        "Create case studies for this segment"
                    ],
                    "metrics": {{
                        "market_size": "30% of total market",
                        "growth_potential": "High"
                    }}
                }}
            ]
            
            Important: Your response must be a valid JSON array starting with [ and ending with ]. Do not include any markdown formatting or code block markers."""
            
        else:  # improvement
            prompt = f"""You are a product improvement analyst. Analyze these form responses and suggest detailed improvements.
            Form Information:
            - Title: {form.title}
            - Description: {form.description}
            - Total Responses: {structured_data['form_info']['total_responses']}
            
            Questions and Answers:
            {json.dumps(structured_data['question_answer_mapping'], indent=2)}
            
            Generate 5 detailed improvement ideas with specific action plans. For each improvement:
            1. Identify the area for improvement
            2. Provide detailed analysis of current issues
            3. Suggest specific, actionable steps
            4. Include priority level and expected impact
            
            Format your response as a JSON array with objects containing:
            - title: Improvement area
            - description: Detailed analysis of current state
            - recommendations: Array of specific, actionable steps
            - metrics: Priority level and expected impact
            
            Example format:
            [
                {{
                    "title": "User Onboarding Experience",
                    "description": "Current onboarding process has 40% drop-off rate after first step",
                    "recommendations": [
                        "Implement interactive tutorials",
                        "Add progress indicators",
                        "Create video guides"
                    ],
                    "metrics": {{
                        "priority": "High",
                        "expected_impact": "Reduce drop-off by 50%"
                    }}
                }}
            ]
            
            Important: Your response must be a valid JSON array starting with [ and ending with ]. Do not include any markdown formatting or code block markers."""
            
        print("Generated prompt, attempting to generate content...")
        print(f"Prompt length: {len(prompt)} characters")
        
        # Generate content using the model
        response = model.generate_content(prompt)
        
        if response and hasattr(response, 'text'):
            try:
                # Clean the response text to remove any markdown formatting
                response_text = response.text.strip()
                if response_text.startswith('```json'):
                    response_text = response_text[7:]
                if response_text.endswith('```'):
                    response_text = response_text[:-3]
                response_text = response_text.strip()
                
                # Parse the response as JSON
                insights = json.loads(response_text)
                print(f"Generated {len(insights)} {insight_type} insights")
                return insights
            except json.JSONDecodeError as e:
                print(f"Error parsing JSON response: {str(e)}")
                print(f"Raw response: {response.text}")
                return []
        else:
            print("No valid response from model")
            return []
            
    except Exception as e:
        print(f"Error in generate_insights_with_gemini: {str(e)}")
        print(f"Error type: {type(e)}")
        return []

def generate_product_insights(answers, form):
    """Generate product-related insights using Gemini"""
    return generate_insights_with_gemini(answers, form, 'product')

def generate_market_segments(answers, form):
    """Generate market segment insights using Gemini"""
    return generate_insights_with_gemini(answers, form, 'market')

def generate_improvement_ideas(answers, form):
    """Generate improvement ideas using Gemini"""
    return generate_insights_with_gemini(answers, form, 'improvement')

def generate_sample_responses():
    """Generate sample form responses for testing insights generation"""
    sample_answers = [
        {
            'question_text': 'How satisfied are you with our product?',
            'answer_text': 'Very satisfied',
            'question_type': 'radio'
        },
        {
            'question_text': 'Which features do you use most frequently?',
            'answer_text': '["Analytics Dashboard", "Automated Reports", "Team Collaboration"]',
            'question_type': 'checkbox'
        },
        {
            'question_text': 'What is your primary use case?',
            'answer_text': 'Business Analytics',
            'question_type': 'text'
        },
        {
            'question_text': 'How many team members use the product?',
            'answer_text': '5-10',
            'question_type': 'radio'
        },
        {
            'question_text': 'What improvements would you like to see?',
            'answer_text': 'Better mobile experience and more integration options',
            'question_type': 'text'
        },
        {
            'question_text': 'What is your industry?',
            'answer_text': 'Technology',
            'question_type': 'radio'
        },
        {
            'question_text': 'How long have you been using our product?',
            'answer_text': '6-12 months',
            'question_type': 'radio'
        },
        {
            'question_text': 'What is your role in the organization?',
            'answer_text': 'Product Manager',
            'question_type': 'radio'
        },
        {
            'question_text': 'Which integrations do you use?',
            'answer_text': '["Slack", "Google Analytics", "Jira"]',
            'question_type': 'checkbox'
        },
        {
            'question_text': 'What is your monthly budget for this tool?',
            'answer_text': '$100-500',
            'question_type': 'radio'
        }
    ]
    return sample_answers

@app.route('/form/<int:form_id>/generate-insights', methods=['POST'])
@login_required
def generate_insights(form_id):
    """Generate business insights from form responses using Gemini"""
    try:
        print("\n=== Starting Insight Generation Process ===")
        form = Form.query.get_or_404(form_id)
        print(f"Found form: {form.title} (ID: {form.id})")
        
        if form.user_id != current_user.id:
            print("Unauthorized access attempt")
            return jsonify({'success': False, 'message': 'Unauthorized'}), 403

        # Get analysis options from request
        data = request.get_json()
        print(f"Request data: {data}")
        analyze_product = data.get('productInsights', True)
        analyze_market = data.get('marketSegments', True)
        analyze_improvements = data.get('improvementIdeas', True)
        print(f"Analysis options - Product: {analyze_product}, Market: {analyze_market}, Improvements: {analyze_improvements}")

        # Get all responses for this form
        responses = Response.query.filter_by(form_id=form_id).all()
        print(f"Found {len(responses)} responses for form {form_id}")
        
        # Get all questions for this form
        questions = Question.query.filter_by(form_id=form_id).all()
        print(f"Found {len(questions)} questions for form {form_id}")

        # Create a structured mapping of questions and their answers
        question_answer_mapping = {}
        
        # First, initialize the mapping with questions
        for question in questions:
            question_answer_mapping[question.id] = {
                'question_text': question.question_text,
                'question_type': question.question_type,
                'answers': []
            }
            print(f"Added question: {question.question_text}")
        
        # Then, add all answers for each question
        for response in responses:
            print(f"\nProcessing response ID: {response.id}")
            for answer in response.answers:
                if answer.question_id in question_answer_mapping:
                    question_answer_mapping[answer.question_id]['answers'].append({
                        'answer_text': answer.answer_text,
                        'submitted_at': response.submitted_at.isoformat()
                    })
                    print(f"Added answer for question {answer.question_id}: {answer.answer_text[:50]}...")

        # Create the final structured data for the API
        structured_data = {
            'form_info': {
                'title': form.title,
                'description': form.description,
                'total_responses': len(responses),
                'created_at': form.created_at.isoformat()
            },
            'question_answer_mapping': question_answer_mapping
        }

        print("\nStructured data for API:")
        print(json.dumps(structured_data, indent=2))

        # Configure Gemini with REST transport
        try:
            api_key = app.config['GOOGLE_API_KEY']
            if not api_key:
                raise ValueError("API key not found in app configuration")
                
            google.generativeai.configure(
                api_key=api_key,
                transport='rest'
            )
            model = google.generativeai.GenerativeModel('gemini-2.0-flash')
            print("Successfully configured Gemini model")
        except Exception as e:
            print(f"Error configuring Gemini: {str(e)}")
            return jsonify({
                'success': False,
                'message': f'Error configuring AI service: {str(e)}'
            }), 500

        # Generate insights based on selected options
        insights = {
            'productInsights': [],
            'marketSegments': [],
            'improvementIdeas': []
        }

        if analyze_product:
            try:
                print("\nGenerating product insights...")
                product_insights = generate_insights_with_gemini(structured_data, form, 'product')
                print(f"Generated {len(product_insights)} product insights")
                insights['productInsights'] = product_insights
            except Exception as e:
                print(f"Error generating product insights: {str(e)}")
                insights['productInsights'] = [{
                    'title': 'Error Generating Product Insights',
                    'description': str(e),
                    'recommendations': ['Please try again later'],
                    'metrics': {'status': 'error'}
                }]
        
        if analyze_market:
            try:
                print("\nGenerating market segments...")
                market_segments = generate_insights_with_gemini(structured_data, form, 'market')
                print(f"Generated {len(market_segments)} market segments")
                insights['marketSegments'] = market_segments
            except Exception as e:
                print(f"Error generating market segments: {str(e)}")
                insights['marketSegments'] = [{
                    'title': 'Error Generating Market Segments',
                    'description': str(e),
                    'recommendations': ['Please try again later'],
                    'metrics': {'status': 'error'}
                }]
        
        if analyze_improvements:
            try:
                print("\nGenerating improvement ideas...")
                improvement_ideas = generate_insights_with_gemini(structured_data, form, 'improvement')
                print(f"Generated {len(improvement_ideas)} improvement ideas")
                insights['improvementIdeas'] = improvement_ideas
            except Exception as e:
                print(f"Error generating improvement ideas: {str(e)}")
                insights['improvementIdeas'] = [{
                    'title': 'Error Generating Improvement Ideas',
                    'description': str(e),
                    'recommendations': ['Please try again later'],
                    'metrics': {'status': 'error'}
                }]

        print("\nFinal insights structure:")
        print(json.dumps(insights, indent=2))

        return jsonify({
            'success': True,
            'productInsights': insights['productInsights'],
            'marketSegments': insights['marketSegments'],
            'improvementIdeas': insights['improvementIdeas']
        })

    except Exception as e:
        print(f"Error generating insights: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500

@app.route('/form/<int:form_id>/export-insights')
@login_required
def export_insights(form_id):
    """Export business insights as a PDF report"""
    try:
        print("\n=== Starting Insights Export Process ===")
        form = Form.query.get_or_404(form_id)
        if form.user_id != current_user.id:
            flash('Unauthorized', 'danger')
            return redirect(url_for('dashboard'))

        # Get all responses for this form
        responses = Response.query.filter_by(form_id=form_id).all()
        print(f"Found {len(responses)} responses for form {form_id}")
        
        # Get all questions for this form
        questions = Question.query.filter_by(form_id=form_id).all()
        print(f"Found {len(questions)} questions for form {form_id}")

        # Create a structured mapping of questions and their answers
        question_answer_mapping = {}
        
        # First, initialize the mapping with questions
        for question in questions:
            question_answer_mapping[question.id] = {
                'question_text': question.question_text,
                'question_type': question.question_type,
                'answers': []
            }
        
        # Then, add all answers for each question
        for response in responses:
            for answer in response.answers:
                if answer.question_id in question_answer_mapping:
                    question_answer_mapping[answer.question_id]['answers'].append({
                        'answer_text': answer.answer_text,
                        'submitted_at': response.submitted_at.isoformat()
                    })

        # Create the final structured data for the API
        structured_data = {
            'form_info': {
                'title': form.title,
                'description': form.description,
                'total_responses': len(responses),
                'created_at': form.created_at.isoformat()
            },
            'question_answer_mapping': question_answer_mapping
        }

        print("Generating insights...")
        
        # Generate all types of insights
        insights = {
            'productInsights': generate_insights_with_gemini(structured_data, form, 'product'),
            'marketSegments': generate_insights_with_gemini(structured_data, form, 'market'),
            'improvementIdeas': generate_insights_with_gemini(structured_data, form, 'improvement')
        }

        print(f"Generated insights: {json.dumps(insights, indent=2)}")

        # Create PDF report
        print("Creating PDF report...")
        pdf_path = create_insights_pdf(form, insights)
        
        print(f"PDF created successfully at: {pdf_path}")
        
        # Return the PDF file
        return send_file(
            pdf_path,
            as_attachment=True,
            download_name=f'business_insights_{form.title}_{datetime.now().strftime("%Y%m%d")}.pdf'
        )

    except Exception as e:
        print(f"Error exporting insights: {str(e)}")
        flash(f'Error exporting insights: {str(e)}', 'danger')
        return redirect(url_for('business_insights'))

def create_insights_pdf(form, insights):
    """Create a PDF report of business insights"""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Preformatted
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    
    # Create PDF file
    export_path = os.path.join('exports', 'business_insights')
    os.makedirs(export_path, exist_ok=True)
    
    filename = f'insights_{form.id}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf'
    pdf_path = os.path.join(export_path, filename)
    
    doc = SimpleDocTemplate(pdf_path, pagesize=letter)
    styles = getSampleStyleSheet()
    
    # Create custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=30,
        textColor=colors.HexColor('#2C3E50')
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=18,
        spaceAfter=15,
        textColor=colors.HexColor('#34495E')
    )
    
    subheading_style = ParagraphStyle(
        'CustomSubHeading',
        parent=styles['Heading3'],
        fontSize=14,
        spaceAfter=10,
        textColor=colors.HexColor('#7F8C8D')
    )
    
    normal_style = ParagraphStyle(
        'CustomNormal',
        parent=styles['Normal'],
        fontSize=11,
        spaceAfter=8,
        textColor=colors.HexColor('#2C3E50')
    )
    
    code_style = ParagraphStyle(
        'CodeStyle',
        parent=styles['Code'],
        fontSize=8,
        fontName='Courier',
        leading=10,
        spaceAfter=8,
        textColor=colors.HexColor('#2C3E50')
    )
    
    story = []
    
    # Title
    story.append(Paragraph(f'Business Insights Report: {form.title}', title_style))
    story.append(Spacer(1, 20))
    
    # Add generation timestamp
    story.append(Paragraph(f'Generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}', normal_style))
    story.append(Spacer(1, 30))
    
    # Executive Summary
    story.append(Paragraph('Executive Summary', heading_style))
    story.append(Spacer(1, 10))
    
    # Add summary of insights
    total_insights = len(insights.get('productInsights', [])) + len(insights.get('marketSegments', [])) + len(insights.get('improvementIdeas', []))
    story.append(Paragraph(f'This report contains {total_insights} key insights across three categories:', normal_style))
    story.append(Paragraph(f'• {len(insights.get("productInsights", []))} Product Insights', normal_style))
    story.append(Paragraph(f'• {len(insights.get("marketSegments", []))} Market Segments', normal_style))
    story.append(Paragraph(f'• {len(insights.get("improvementIdeas", []))} Improvement Ideas', normal_style))
    story.append(Spacer(1, 20))
    
    # Product Insights
    if insights.get('productInsights'):
        story.append(Paragraph('Product Insights', heading_style))
        story.append(Spacer(1, 10))
        
        for insight in insights['productInsights']:
            story.append(Paragraph(insight['title'], subheading_style))
            story.append(Paragraph(insight['description'], normal_style))
            
            if insight.get('metrics'):
                metrics_data = [[Paragraph('Metric', subheading_style), Paragraph('Value', subheading_style)]]
                for key, value in insight['metrics'].items():
                    metrics_data.append([Paragraph(key.replace('_', ' ').title(), normal_style), 
                                       Paragraph(str(value), normal_style)])
                
                metrics_table = Table(metrics_data, colWidths=[2*inch, 2*inch])
                metrics_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ECF0F1')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#2C3E50')),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 12),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                    ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor('#2C3E50')),
                    ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                    ('FONTSIZE', (0, 1), (-1, -1), 10),
                    ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#BDC3C7'))
                ]))
                story.append(metrics_table)
                story.append(Spacer(1, 10))
            
            if insight.get('recommendations'):
                story.append(Paragraph('Recommendations:', subheading_style))
                for rec in insight['recommendations']:
                    story.append(Paragraph(f'• {rec}', normal_style))
            story.append(Spacer(1, 20))
    
    # Market Segments
    if insights.get('marketSegments'):
        story.append(Paragraph('Market Segments', heading_style))
        story.append(Spacer(1, 10))
        
        for segment in insights['marketSegments']:
            story.append(Paragraph(segment['title'], subheading_style))
            story.append(Paragraph(segment['description'], normal_style))
            
            if segment.get('metrics'):
                metrics_data = [[Paragraph('Metric', subheading_style), Paragraph('Value', subheading_style)]]
                for key, value in segment['metrics'].items():
                    metrics_data.append([Paragraph(key.replace('_', ' ').title(), normal_style), 
                                       Paragraph(str(value), normal_style)])
                
                metrics_table = Table(metrics_data, colWidths=[2*inch, 2*inch])
                metrics_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ECF0F1')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#2C3E50')),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 12),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                    ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor('#2C3E50')),
                    ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                    ('FONTSIZE', (0, 1), (-1, -1), 10),
                    ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#BDC3C7'))
                ]))
                story.append(metrics_table)
                story.append(Spacer(1, 10))
            
            if segment.get('recommendations'):
                story.append(Paragraph('Recommendations:', subheading_style))
                for rec in segment['recommendations']:
                    story.append(Paragraph(f'• {rec}', normal_style))
            story.append(Spacer(1, 20))
    
    # Improvement Ideas
    if insights.get('improvementIdeas'):
        story.append(Paragraph('Improvement Ideas', heading_style))
        story.append(Spacer(1, 10))
        
        for idea in insights['improvementIdeas']:
            story.append(Paragraph(idea['title'], subheading_style))
            story.append(Paragraph(idea['description'], normal_style))
            
            if idea.get('metrics'):
                metrics_data = [[Paragraph('Metric', subheading_style), Paragraph('Value', subheading_style)]]
                for key, value in idea['metrics'].items():
                    metrics_data.append([Paragraph(key.replace('_', ' ').title(), normal_style), 
                                       Paragraph(str(value), normal_style)])
                
                metrics_table = Table(metrics_data, colWidths=[2*inch, 2*inch])
                metrics_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ECF0F1')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#2C3E50')),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 12),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                    ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor('#2C3E50')),
                    ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                    ('FONTSIZE', (0, 1), (-1, -1), 10),
                    ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#BDC3C7'))
                ]))
                story.append(metrics_table)
                story.append(Spacer(1, 10))
            
            if idea.get('recommendations'):
                story.append(Paragraph('Recommendations:', subheading_style))
                for rec in idea['recommendations']:
                    story.append(Paragraph(f'• {rec}', normal_style))
            story.append(Spacer(1, 20))
    
    # Add Appendix with Raw Data
    story.append(Paragraph('Appendix: Raw Data', heading_style))
    story.append(Spacer(1, 10))
    
    # Get all questions and answers for this form
    questions = Question.query.filter_by(form_id=form.id).all()
    responses = Response.query.filter_by(form_id=form.id).all()
    
    # Create question-answer mapping
    question_answer_mapping = {}
    for question in questions:
        question_answer_mapping[question.id] = {
            'question_text': question.question_text,
            'question_type': question.question_type,
            'answers': []
        }
        
        # Get all answers for this question
        for response in responses:
            answer = Answer.query.filter_by(
                response_id=response.id,
                question_id=question.id
            ).first()
            
            if answer:
                question_answer_mapping[question.id]['answers'].append({
                    'answer_text': answer.answer_text,
                    'submitted_at': response.submitted_at.isoformat()
                })
    
    # Create the complete data structure
    raw_data = {
        'form_info': {
            'title': form.title,
            'description': form.description,
            'total_responses': len(responses),
            'created_at': form.created_at.isoformat()
        },
        'question_answer_mapping': question_answer_mapping,
        'insights': insights
    }
    
    # Format the JSON data with proper indentation
    json_data = json.dumps(raw_data, indent=2)
    
    # Add the JSON data as preformatted text
    story.append(Paragraph('Complete Question-Answer Mapping and Insights Data:', subheading_style))
    story.append(Spacer(1, 5))
    story.append(Preformatted(json_data, code_style))
    
    # Build PDF
    doc.build(story)
    return pdf_path
from flask import render_template_string
view_data_storage = []
@app.route('/view_data', methods=['GET', 'POST'])
def view_data():
    if request.method == 'POST':
        data = request.get_json()
        if not data or 'form_id' not in data or 'user_id' not in data or 'company_name' not in data:
            return jsonify({"error": "Missing data"}), 400

        entry = {
            "form_id": data['form_id'],
            "user_id": data['user_id'],
            "company_name": data['company_name']
        }
        view_data_storage.append(entry)
        print("Stored entry:", entry)
        return jsonify({"status": "success"}), 200

    # GET request: Show all stored entries
    html = """
    <!doctype html>
    <html>
    <head>
        <title>Submit Events</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; }
            ul { line-height: 1.6; font-size: 18px; }
            li { margin-bottom: 4px; }
        </style>
    </head>
    <body>
        <h2>All Submit Button Clicks</h2>
        <ul>
        {% for entry in entries %}
            <li><strong>{{ entry.form_id }}</strong> → {{ entry.user_id }} → {{ entry.company_name }}</li>
        {% endfor %}
        </ul>
        <p><strong>Total:</strong> {{ entries|length }}</p>
    </body>
    </html>
    """
    return render_template_string(html, entries=view_data_storage)

# Configure Google's Generative AI
def configure_genai():
    try:
        # Use GOOGLE_API_KEY instead of GEMINI_API_KEY
        genai.configure(api_key=app.config['GOOGLE_API_KEY'])
        # Use the previously used model
        model = genai.GenerativeModel('gemini-2.0-flash')
        return model
    except Exception as e:
        app.logger.error(f"Error configuring Google AI: {str(e)}")
        return None

def generate_mindmap(prompt):
    """Generate a mind map structure from the prompt using Google AI."""
    try:
        model = configure_genai()
        if not model:
            app.logger.error("Failed to configure Google AI model")
            return None

        # Create a prompt for the AI to generate a mind map structure
        mindmap_prompt = f"""
        You are a form creation expert. Create a structured form based on this description: {prompt}
        
        Return ONLY a JSON object with the following structure, no other text:
        {{
            "title": "Form Title",
            "description": "Form Description",
            "sections": [
                {{
                    "title": "Section Title",
                    "questions": [
                        {{
                            "text": "Question Text",
                            "type": "text/multiple_choice/checkbox",
                            "required": true/false,
                            "options": ["option1", "option2"] // for multiple choice/checkbox
                        }}
                    ]
                }}
            ]
        }}
        
        Guidelines:
        1. Break down the form into logical sections
        2. Use appropriate question types (text, multiple_choice, checkbox)
        3. Add relevant options for multiple choice questions
        4. Mark essential questions as required
        5. Keep the JSON structure clean and valid
        """

        # Optimized generation config for gemini-2.0-flash
        generation_config = {
            "temperature": 0.3,  # Lower temperature for more focused output
            "top_p": 0.95,
            "top_k": 40,
            "max_output_tokens": 1024,  # Reduced for faster response
            "candidate_count": 1
        }

        safety_settings = [
            {
                "category": "HARM_CATEGORY_HARASSMENT",
                "threshold": "BLOCK_MEDIUM_AND_ABOVE"
            },
            {
                "category": "HARM_CATEGORY_HATE_SPEECH",
                "threshold": "BLOCK_MEDIUM_AND_ABOVE"
            },
            {
                "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                "threshold": "BLOCK_MEDIUM_AND_ABOVE"
            },
            {
                "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                "threshold": "BLOCK_MEDIUM_AND_ABOVE"
            }
        ]

        # Generate content with optimized settings
        response = model.generate_content(
            mindmap_prompt,
            generation_config=generation_config,
            safety_settings=safety_settings,
            stream=False  # Disable streaming for faster response
        )

        # Extract the JSON from the response
        try:
            # Clean the response text to ensure it's valid JSON
            response_text = response.text.strip()
            # Remove any markdown code block indicators and extra whitespace
            response_text = response_text.replace('```json', '').replace('```', '').strip()
            # Remove any leading/trailing quotes if present
            response_text = response_text.strip('"\'')
            
            mindmap_data = json.loads(response_text)
            
            # Validate the structure
            required_keys = ['title', 'description', 'sections']
            if not all(key in mindmap_data for key in required_keys):
                app.logger.error("Invalid mind map structure: missing required keys")
                return None
                
            if not isinstance(mindmap_data['sections'], list):
                app.logger.error("Invalid mind map structure: sections must be a list")
                return None
                
            return mindmap_data
            
        except json.JSONDecodeError as e:
            app.logger.error(f"Failed to parse AI response as JSON: {str(e)}")
            app.logger.error(f"Raw response: {response.text}")
            return None
            
    except Exception as e:
        app.logger.error(f"Error generating mind map: {str(e)}")
        return None

def create_mindmap_visualization(mindmap_data):
    """Create a visual representation of the mind map."""
    try:
        G = nx.DiGraph()
        
        # Add root node
        G.add_node("root", label=mindmap_data["title"])
        
        # Add sections and questions
        for section in mindmap_data["sections"]:
            section_id = f"section_{section['title']}"
            G.add_node(section_id, label=section["title"])
            G.add_edge("root", section_id)
            
            for question in section["questions"]:
                question_id = f"q_{question['text'][:20]}"
                G.add_node(question_id, label=question["text"])
                G.add_edge(section_id, question_id)
        
        # Create the visualization
        plt.figure(figsize=(12, 8))
        pos = nx.spring_layout(G, k=1, iterations=50)
        
        # Draw nodes
        nx.draw_networkx_nodes(G, pos, node_color='lightblue', 
                             node_size=2000, alpha=0.7)
        
        # Draw edges
        nx.draw_networkx_edges(G, pos, edge_color='gray', 
                             arrows=True, arrowsize=20)
        
        # Draw labels
        labels = nx.get_node_attributes(G, 'label')
        nx.draw_networkx_labels(G, pos, labels, font_size=8)
        
        # Save to buffer
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight', dpi=300)
        buf.seek(0)
        
        # Convert to base64
        img_str = base64.b64encode(buf.read()).decode()
        plt.close()
        
        return f'<img src="data:image/png;base64,{img_str}" class="img-fluid" alt="Mind Map">'
    except Exception as e:
        app.logger.error(f"Error creating mind map visualization: {str(e)}")
        return None

def generate_form_from_mindmap(mindmap_data):
    """Generate a form preview from the mind map data."""
    try:
        html = f"""
        <div class="form-preview-content">
            <h3 class="mb-4">{mindmap_data['title']}</h3>
            <p class="text-muted mb-4">{mindmap_data['description']}</p>
        """
        
        for section in mindmap_data["sections"]:
            html += f"""
            <div class="form-section mb-4">
                <h4 class="mb-3">{section['title']}</h4>
            """
            
            for question in section["questions"]:
                html += f"""
                <div class="form-group mb-3">
                    <label class="form-label">
                        {question['text']}
                        {f'<span class="text-danger">*</span>' if question.get('required', False) else ''}
                    </label>
                """
                
                if question["type"] == "text":
                    html += f"""
                    <input type="text" class="form-control" 
                           placeholder="Enter your answer" 
                           {'required' if question.get('required', False) else ''}>
                    """
                elif question["type"] in ["multiple_choice", "checkbox"]:
                    for option in question.get("options", []):
                        input_type = "radio" if question["type"] == "multiple_choice" else "checkbox"
                        html += f"""
                        <div class="form-check">
                            <input class="form-check-input" type="{input_type}" 
                                   name="q_{question['text'][:20]}" 
                                   id="q_{question['text'][:20]}_{option[:20]}"
                                   {'required' if question.get('required', False) else ''}>
                            <label class="form-check-label" for="q_{question['text'][:20]}_{option[:20]}">
                                {option}
                            </label>
                        </div>
                        """
                
                html += "</div>"
            
            html += "</div>"
        
        html += "</div>"
        return html
    except Exception as e:
        app.logger.error(f"Error generating form preview: {str(e)}")
        return None

@app.route('/create-form-ai', methods=['GET', 'POST'])
@login_required
def create_form_ai():
    """Handle AI form creation."""
    if request.method == 'POST':
        prompt = request.form.get('prompt')
        include_mindmap = request.form.get('include_mindmap', 'true') == 'true'

        if not prompt:
            flash('Please provide a description for the form.', 'error')
            return redirect(url_for('create_form_ai'))

        # Generate mind map structure
        mindmap_data = generate_mindmap(prompt)
        if not mindmap_data:
            flash('Failed to generate form structure. Please try again.', 'error')
            return redirect(url_for('create_form_ai'))

        # Store the mind map data in session for form creation
        session['mindmap_data'] = mindmap_data
        score = request.form.get('score', 100)
        session['score'] = int(score)
        # Generate visualization if requested
        mindmap_image = None
        if include_mindmap:
            mindmap_image = create_mindmap_visualization(mindmap_data)

        # Generate form preview
        form_preview = generate_form_from_mindmap(mindmap_data)

        return render_template('create_form_ai.html',
                             mindmap_data=mindmap_data,
                             mindmap_image=mindmap_image,
                             form_preview=form_preview)

    return render_template('create_form_ai.html')

@app.route('/create-form-from-ai', methods=['POST'])
@login_required
def create_form_from_ai():
    """Create a form from the AI-generated mind map data."""
    try:
        # Get the mind map data from the session
        mindmap_data = session.get('mindmap_data')
        
        if not mindmap_data:
            flash('No form data found. Please generate a form first.', 'error')
            return redirect(url_for('create_form_ai'))
        score = session.get('score', 100)
        form = Form(
            title=mindmap_data['title'],
            description=mindmap_data['description'],
            user_id=current_user.id,
            created_at=datetime.utcnow(),
            score=int(score) 
        )
        db.session.add(form)
        db.session.flush()  # Get the form ID

        # Add questions from each section
        order = 1
        for section in mindmap_data['sections']:
            for question_data in section['questions']:
                question = Question(
                    form_id=form.id,
                    question_text=question_data['text'],
                    question_type=question_data['type'],
                    required=question_data.get('required', False),
                    order=order
                )
                
                # Handle options for multiple choice and checkbox questions
                if question_data['type'] in ['multiple_choice', 'checkbox'] and 'options' in question_data:
                    question.set_options(question_data['options'])
                
                db.session.add(question)
                order += 1

        # Commit all changes
        db.session.commit()

        # Clear the mind map data from session
        session.pop('mindmap_data', None)

        flash('Form created successfully!', 'success')
        return redirect(url_for('dashboard'))

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error creating form from AI: {str(e)}")
        flash('An error occurred while creating the form. Please try again.', 'error')
        return redirect(url_for('create_form_ai'))

@app.route('/chat', methods=['POST'])
@login_required
def chat():
    """Handle chat messages using Gemini AI."""
    try:
        data = request.get_json()
        message = data.get('message')
        
        if not message:
            return jsonify({'success': False, 'error': 'No message provided'})
        
        # Configure Gemini
        model = configure_genai()
        if not model:
            return jsonify({'success': False, 'error': 'Failed to configure AI model'})
        
        # Create a prompt for the AI
        prompt = f"""
        You are a helpful AI assistant for a form creation platform. The user is asking: {message}
        
        Guidelines:
        1. Be concise and clear in your responses
        2. Focus on helping with form creation, management, and troubleshooting
        3. If the question is not related to forms, politely redirect to form-related topics
        4. Use markdown formatting for better readability
        5. If you're not sure about something, admit it and suggest contacting support
        
        Provide a helpful response:
        """
        
        # Generate response
        response = model.generate_content(
            prompt,
            generation_config={
                "temperature": 0.7,
                "top_p": 0.8,
                "top_k": 40,
                "max_output_tokens": 1024,
            }
        )
        
        return jsonify({
            'success': True,
            'response': response.text
        })
        
    except Exception as e:
        app.logger.error(f"Error in chat: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'An error occurred while processing your message'
        })

@app.route('/send_to_surveytitans', methods=['POST'])
def send_to_surveytitans():
    print("here1")
    try:
        data = request.get_json()
        formId = data.get('formId')
        userId = data.get('userId')
        companyName = data.get('companyName')

        # ✅ Print the values
        print(f"Form ID: {formId}")
        print(f"User ID: {userId}")
        print(f"Company Name: {companyName}")

        if not all([formId, userId, companyName]):
            return jsonify({'status': 'error', 'message': 'Missing fields'}), 400
        payout = Form.query.get(formId).score
        target_url = f"https://surveytitans.com/spb/325455fec74bf41ae1db1cb05b3a7f9d?username=Ayush&payout={payout/100:.2f}"
        payload = {
            "formId": formId,
            "userId": userId,
            "companyName": companyName
        }

        response = requests.post(target_url, json=payload)

        # ✅ Log the response from SurveyTitans
        print(f"Sent to SurveyTitans: {response.status_code} - {response.text}")

        return jsonify({
            'status': 'success',
            'response_code': response.status_code,
            'response_text': response.text
        })

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
@app.route('/merge_form/<int:form_id>', methods=['POST'])
def merge_form(form_id):
    merge_url = request.form.get('merge_url')
    if not merge_url:
        flash("Please enter a URL to merge with.", "danger")
        return redirect(request.referrer)
    form = Form.query.get_or_404(form_id)
    form.merged_url = merge_url  # ✅ save to database
    db.session.commit()  
    flash(f"Form {form_id} successfully merged with Form {merge_url}.", "success")
    print(f"Merge URL for form {form_id}: {merge_url}")
    return redirect(request.referrer) 
# @app.route('/oliver_ads', methods=['POST'])
# def oliver_ads():
#     data = request.get_json()
#     form_clone_id = data.get('formClone_RespondeId')
#     print("Received formClone_RespondeId:", form_clone_id)
#     return jsonify({"status": "success", "received": form_clone_id})
@app.route('/oliver_ads', methods=['POST'])
def oliver_ads():
    data = request.get_json()
    form_clone_id = data.get('formClone_RespondeId')
    print("Received formClone_RespondeId:", form_clone_id)

    if not form_clone_id:
        return jsonify({"status": "error", "message": "No formClone_RespondeId provided"}), 400

    # Try to find the Response with this id
    response_obj = Response.query.filter_by(id=form_clone_id).first()

    if not response_obj:
        return jsonify({"status": "error", "message": "Response not found"}), 404

    # Update the status field to "success"
    response_obj.status = "success"

    # Commit the update to the database
    db.session.commit()

    return jsonify({"status": "success", "updated_response_id": form_clone_id})

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        # Clear all existing templates and recreate
        FormTemplate.query.delete()
        db.session.commit()
        initialize_templates()  # Add this line to initialize templates
    app.run(host='0.0.0.0',port=8080)
