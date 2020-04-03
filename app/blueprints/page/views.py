from flask import Blueprint, render_template, flash
from app.extensions import cache, timeout
from config import settings
from app.extensions import db, csrf
from flask import redirect, url_for, request, current_app
from flask_login import current_user, login_required
import requests
import ast
import json
import traceback
from sqlalchemy import and_, exists, text
from importlib import import_module
import os
import random

page = Blueprint('page', __name__, template_folder='templates')


@page.route('/')
def home():
    test = not current_app.config.get('PRODUCTION')
    if current_user.is_authenticated:
        return redirect(url_for('user.dashboard'))

    return render_template('page/index.html',
                           plans=settings.STRIPE_PLANS)


@page.route('/terms')
def terms():
    return render_template('page/terms.html')


@page.route('/privacy')
def privacy():
    return render_template('page/privacy.html')


@page.route('/index')
def index():
    return render_template('page/index.html', plans=settings.STRIPE_PLANS)


# Callbacks.
@page.route('/callback/<app>', methods=['GET', 'POST'])
@csrf.exempt
def callback(app):
    module = import_module("app.blueprints.api.apps." + app + "." + app)
    app_callback = getattr(module, 'callback')
    return app_callback(request)


# Webhooks -------------------------------------------------------------------
@page.route('/webhook/<app>', methods=['GET','POST'])
@csrf.exempt
def webhook(app):
    try:
        module = import_module("app.blueprints.api.apps." + app + ".webhook")
        call_webhook = getattr(module, 'webhook')

        return call_webhook(request)
    except Exception:
        return json.dumps({'success': False}), 500, {'ContentType': 'application/json'}


# Pagination for /drops route
class PageResult:
    def __init__(self, data, tld, page = 1, number = 20):
        self.__dict__ = dict(zip(['data', 'tld', 'page', 'number'], [data, tld, page, number]))
        self.full_listing = [self.data[i:i+number] for i in range(0, len(self.data), number)]
    def __iter__(self):
        for i in self.full_listing[self.page-1]:
            yield i
    def __repr__(self): #used for page linking
        # return "/drops/{0}/{1}".format(self.tld, str(self.page+1)) #view the next page
        return '/drops/' + str(self.tld) + '/' + str(int(self.page)+1)