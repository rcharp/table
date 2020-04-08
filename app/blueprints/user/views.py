from flask import (
    Blueprint,
    redirect,
    request,
    flash,
    Markup,
    url_for,
    render_template,
    current_app,
    json,
    jsonify,
    session)
from flask_login import (
    login_required,
    login_user,
    current_user,
    logout_user)

import time
import random

from lib.safe_next_url import safe_next_url
from app.blueprints.user.decorators import anonymous_required
from app.blueprints.user.models import User
from app.blueprints.user.forms import (
    LoginForm,
    BeginPasswordResetForm,
    PasswordResetForm,
    SignupForm,
    WelcomeForm,
    UpdateCredentials)

import re
import os
import pytz
import stripe
import datetime
from datetime import datetime as dt
from app.extensions import cache, csrf, timeout, db
from importlib import import_module
from sqlalchemy import or_, and_, exists, inspect
from app.blueprints.billing.charge import (
    stripe_checkout,
    create_payment,
    delete_payment,
    charge_card,
    get_payment_method,
    get_card
)
from app.blueprints.api.api_functions import print_traceback
from app.blueprints.api.models.domains import Domain
from app.blueprints.page.date import get_utc_date_today

user = Blueprint('user', __name__, template_folder='templates')

# Login and Credentials -------------------------------------------------------------------
@user.route('/login', methods=['GET', 'POST'])
@anonymous_required()
# @cache.cached(timeout=timeout)
@csrf.exempt
def login():

    # This redirects to the link that the button was sending to before login
    form = LoginForm(next=request.args.get('next'))

    # This redirects to dashboard always.
    # form = LoginForm(next=url_for('user.dashboard'))

    if form.validate_on_submit():

        u = User.find_by_identity(request.form.get('identity'))

        if u and u.is_active() and u.authenticated(password=request.form.get('password')):
            # As you can see remember me is always enabled, this was a design
            # decision I made because more often than not users want this
            # enabled. This allows for a less complicated login form.
            #
            # If however you want them to be able to select whether or not they
            # should remain logged in then perform the following 3 steps:
            # 1) Replace 'True' below with: request.form.get('remember', False)
            # 2) Uncomment the 'remember' field in user/forms.py#LoginForm
            # 3) Add a checkbox to the login form with the id/name 'remember'
            if login_user(u, remember=True) and u.is_active():
                u.update_activity_tracking(request.remote_addr)

                next_url = request.form.get('next')

                if next_url == url_for('user.login') or next_url == '' or next_url is None:
                    next_url = url_for('user.dashboard')

                if next_url:
                    return redirect(safe_next_url(next_url), code=307)

                if current_user.role == 'admin':
                    return redirect(url_for('admin.dashboard'))
            else:
                flash('This account has been disabled.', 'error')
        else:
            flash('Your username/email or password is incorrect.', 'error')

    else:
        if len(form.errors) > 0:
            print(form.errors)

    return render_template('user/login.html', form=form)


@user.route('/logout')
@login_required
# @cache.cached(timeout=timeout)
def logout():
    logout_user()

    flash('You have been logged out.', 'success')
    return redirect(url_for('user.login'))


@user.route('/account/begin_password_reset', methods=['GET', 'POST'])
@anonymous_required()
def begin_password_reset():
    form = BeginPasswordResetForm()

    if form.validate_on_submit():
        u = User.initialize_password_reset(request.form.get('identity'))

        flash('An email has been sent to {0}.'.format(u.email), 'success')
        return redirect(url_for('user.login'))

    return render_template('user/begin_password_reset.html', form=form)


@user.route('/account/password_reset', methods=['GET', 'POST'])
@anonymous_required()
def password_reset():
    form = PasswordResetForm(reset_token=request.args.get('reset_token'))

    if form.validate_on_submit():
        u = User.deserialize_token(request.form.get('reset_token'))

        if u is None:
            flash('Your reset token has expired or was tampered with.',
                  'error')
            return redirect(url_for('user.begin_password_reset'))

        form.populate_obj(u)
        u.password = User.encrypt_password(request.form.get('password'))
        u.save()

        if login_user(u):
            flash('Your password has been reset.', 'success')
            return redirect(url_for('user.dashboard'))

    return render_template('user/password_reset.html', form=form)


@user.route('/signup', methods=['GET', 'POST'])
@anonymous_required()
@csrf.exempt
# @cache.cached(timeout=timeout)
def signup():
    form = SignupForm()

    if form.validate_on_submit():
        if db.session.query(exists().where(User.email == request.form.get('email'))).scalar():
            flash('There is already an account with this email. Please login.', 'error')
            return redirect(url_for('user.login'))

        u = User()

        form.populate_obj(u)
        u.password = User.encrypt_password(request.form.get('password'))
        u.save()

        if login_user(u):

            from app.blueprints.user.tasks import send_welcome_email
            from app.blueprints.contact.mailerlite import create_subscriber

            send_welcome_email.delay(current_user.email)
            create_subscriber(current_user.email)

            flash("You've successfully signed up!", 'success')
            return redirect(url_for('user.dashboard'))

    return render_template('user/signup.html', form=form)


@user.route('/welcome', methods=['GET', 'POST'])
@login_required
def welcome():
    if current_user.username:
        flash('You already picked a username.', 'warning')
        return redirect(url_for('user.dashboard'))

    form = WelcomeForm()

    if form.validate_on_submit():
        current_user.username = request.form.get('username')
        current_user.save()

        flash('Your username has been set.', 'success')
        return redirect(url_for('user.dashboard'))

    return render_template('user/welcome.html', form=form, payment=current_user.payment_id)


@user.route('/settings/update_credentials', methods=['GET', 'POST'])
@login_required
def update_credentials():
    form = UpdateCredentials(current_user, uid=current_user.id)

    if form.validate_on_submit():
        new_password = request.form.get('password', '')
        current_user.email = request.form.get('email')

        if new_password:
            current_user.password = User.encrypt_password(new_password)

        current_user.save()

        flash('Your sign in settings have been updated.', 'success')
        return redirect(url_for('user.dashboard'))

    return render_template('user/update_credentials.html', form=form)


# Dashboard -------------------------------------------------------------------
@user.route('/dashboard', methods=['GET','POST'])
@login_required
@csrf.exempt
def dashboard():
    if current_user.role == 'admin':
        return redirect(url_for('admin.dashboard'))

    from app.blueprints.api.api_functions import  get_tables

    # Which table are we using?
    tables = get_tables()

    return render_template('user/dashboard.html', current_user=current_user,
                           tables=tables
                           )


# View Sheet -------------------------------------------------------------------
@user.route('/table/<table_name>', methods=['GET','POST'])
@login_required
@csrf.exempt
def table(table_name):
    if current_user.role == 'admin':
        return redirect(url_for('admin.dashboard'))

    from app.blueprints.api.api_functions import get_col_types, generate_id, get_rows, get_columns, get_table, count_rows

    # Which table are we using?
    # table_name = 'domains'
    table = get_table(table_name)

    limit = True
    lim = 50

    lim = None if not limit else lim

    cols, columns = get_columns(table)
    rows = get_rows(table, columns, lim)

    types = get_col_types()
    row_id = generate_id()

    return render_template('user/sheet.html', current_user=current_user,
                           cols=cols,
                           rows=rows,
                           table_name=table_name,
                           types=types,
                           new_row_id=row_id,
                           row_count=count_rows(table))


# Actions -------------------------------------------------------------------
@user.route('/create_table', methods=['GET','POST'])
@csrf.exempt
def create_table():
    if request.method == 'POST':
        if 'table_name' in request.form:
            try:
                from app.blueprints.api.api_functions import create_table
                table_name = request.form['table_name']

                result = create_table(table_name, current_user.id)
                return jsonify({'result': result})
            except Exception as e:
                print_traceback(e)

        return redirect(url_for('user.dashboard'))
    return render_template('user/dashboard.html', current_user=current_user)


@user.route('/update_table', methods=['GET','POST'])
@csrf.exempt
def update_table():
    if request.method == 'POST':
        if 'row' in request.form and 'val' in request.form and 'col' in request.form:
            try:
                from app.blueprints.api.api_functions import update_row
                row = request.form['row']
                val = request.form['val']
                col = request.form['col']

                result = update_row(row, val, col)
                return jsonify({'result': result})
            except Exception as e:
                print_traceback(e)
                return jsonify({'result': False})

        return redirect(url_for('user.dashboard'))
    return render_template('user/dashboard.html', current_user=current_user)


@user.route('/save_new_row', methods=['GET','POST'])
@csrf.exempt
def save_new_row():
    if request.method == 'POST':
        if 'row-id' in request.form:
            id = request.form['row-id']
            from app.blueprints.api.api_functions import update_row
            result = update_row(id, None, None)
            return jsonify({'result': result})
    return redirect(url_for('user.dashboard'))


@user.route('/delete_rows', methods=['GET','POST'])
@csrf.exempt
def delete_rows():
    if request.method == 'POST':
        if 'rows' in request.form:
            rows = json.loads(request.form['rows'])

            from app.blueprints.api.api_functions import delete_rows
            result = delete_rows(rows)
            return jsonify({'result': result})
    return redirect(url_for('user.dashboard'))


@user.route('/update_column', methods=['GET','POST'])
@csrf.exempt
def update_column():
    try:
        print(request.form)
        if request.method == 'POST':
            if 'column_name' in request.form and 'old_column_name' in request.form and 'selected_type' in request.form and 'table_name' in request.form:
                col = request.form['column_name']
                old = request.form['old_column_name']
                type = request.form['selected_type']
                table = request.form['table_name']

                from app.blueprints.api.api_functions import update_column
                result = update_column(table, col, old, type)

                return jsonify({'result': result})
    except Exception as e:
        print_traceback(e)
        return jsonify({'result': False})


@user.route('/delete_column', methods=['GET','POST'])
@csrf.exempt
def delete_column():
    if request.method == 'POST':
        if 'col' in request.form:
            col = json.loads(request.form['col'])

            from app.blueprints.api.api_functions import delete_column
            result = delete_rows(rows)
            return jsonify({'result': result})
    return redirect(url_for('user.dashboard'))


@user.route('/new_row_id', methods=['GET','POST'])
@csrf.exempt
def new_row_id():
    from app.blueprints.api.api_functions import generate_id
    id = generate_id()
    return jsonify({'result': id})


# Settings -------------------------------------------------------------------
@user.route('/settings', methods=['GET','POST'])
@login_required
@csrf.exempt
def settings():

    if current_user.role == 'admin':
        return redirect(url_for('admin.dashboard'))

    c = Customer.query.filter(Customer.user_id == current_user.id).scalar()
    card = get_card(c)

    return render_template('user/settings.html', current_user=current_user, card=card)


# Contact us -------------------------------------------------------------------
@user.route('/contact', methods=['GET','POST'])
@csrf.exempt
def contact():
    if request.method == 'POST':
        from app.blueprints.user.tasks import send_contact_us_email
        send_contact_us_email.delay(request.form['email'], request.form['message'])

        flash('Thanks for your email! You can expect a response shortly.', 'success')
        return redirect(url_for('user.contact'))
    return render_template('user/contact.html', current_user=current_user)
