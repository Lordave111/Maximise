import os
import re
import uuid
import json
import requests
from urllib.parse import quote, parse_qsl, urlencode, urlsplit, urlunsplit

from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_login import LoginManager, login_user, logout_user, current_user, UserMixin, login_required
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or os.urandom(32)
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = os.environ.get('UPLOAD_FOLDER', os.path.join(os.getcwd(), 'static', 'uploads'))

def get_database_url():
    value = (os.environ.get('DATABASE_URL') or '').strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}: value = value[1:-1].strip()
    if not value: return 'sqlite:///maximise.db'
    if value.startswith('postgres://'): return value.replace('postgres://', 'postgresql+psycopg://', 1)
    if value.startswith('postgresql://') and '+psycopg' not in value: return value.replace('postgresql://', 'postgresql+psycopg://', 1)
    if value.startswith('mysql://'): value = value.replace('mysql://', 'mysql+pymysql://', 1)
    if value.startswith('mysql+pymysql://'):
        parsed = urlsplit(value); query = []
        for key, val in parse_qsl(parsed.query, keep_blank_values=True):
            if key.lower().replace('_', '-') in {'ssl-mode', 'sslmode'}: continue
            query.append((key, val))
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))
    return value
