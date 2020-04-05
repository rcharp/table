import re
import sys
import time
import pytz
import string
import random
import requests
import traceback
from datetime import datetime
from collections import defaultdict
from app.extensions import db
from sqlalchemy import exists, and_, or_, inspect, asc
from flask import current_app, jsonify, make_response
from importlib import import_module
from app.blueprints.page.date import get_dt_string, is_datetime, format_datetime
from flask_login import current_user


# Create a distinct integration id for the integration.
def generate_id(size=7, chars=string.digits):
    # Generate a random 7-character user id
    id = int(''.join(random.choice(chars) for _ in range(size)))

    from app.blueprints.api.models.domains import Domain

    # Check to make sure there isn't already that id in the database
    if not db.session.query(exists().where(Domain.id == id)).scalar():
        return id
    else:
        generate_id()


def get_rows(d):
    rows = list()

    # Get the rows and the columns
    domains = d.query.order_by(asc(d.created_on)).all()
    columns = d.__table__.columns

    for domain in domains:

        # False is the first item in each row, which is the select checkbox
        data = [False]

        for column in columns:

            # Get the column's value for the row
            e = getattr(domain, column.name)

            # Format any dates
            if is_datetime(e):
                e = format_datetime(e)

            # Add the column's value to the list
            data.append(e)

        rows.append(data)

    # Add a blank row to the list
    add_blank_row(rows, columns)
    return rows


def add_blank_row(rows, columns):
    data = [False]
    for column in columns:
        data.append(None)
    rows.append(data)


def get_columns(d):

    # Make the first column the select boxes
    # cols = list()
    cols = [{'title': ' ', 'type': 'checkbox', 'width': 50}]

    # Get the columns
    columns = d.__table__.columns
    for column in columns:
        width = 175
        options = {}
        type = str(column.type).lower().strip()
        if type == 'varchar(255)': type = 'text'

        # Format boolean columns
        if type == 'boolean':
            type = 'checkbox'
            width = 100

        # Format date columns
        if type == 'date' or type == 'datetime':
            type = 'calendar'
            options.update({'today': True, 'format': 'MM/DD/YYYY'})

        # Make created and updated columns readonly
        if column.name == 'created_on' or column.name == 'updated_on':
            options.update({'readOnly': True})

        # Create a dictionary for each column name and its type
        cols.append({'title': format_column_name(column.name), 'type': type, 'options': options, 'width': width})

    return cols


def update_row(id, val, col):
    try:

        # Get the corresponding item from the table
        from app.blueprints.api.models.domains import Domain

        if not db.session.query(exists().where(Domain.id == id)).scalar():
            d = Domain()
            d.id = id
            d.save()

            return True
        else:
            d = Domain.query.filter(Domain.id == id).scalar()

            # Handle booleans
            if val == 'true': val = True
            elif val == 'false': val = False

            # If the value has been changed, then update the table
            if getattr(d, col) != val:
                setattr(d, col, val)
                d.save()

                return True
        return False
    except Exception as e:
        print_traceback(e)
        return False


def delete_rows(rows):
    from app.blueprints.api.models.domains import Domain
    for row in rows:
        d = Domain.query.filter(Domain.id == row).scalar()
        d.delete()
    return True


def delete_column(rows):
    from app.blueprints.api.models.domains import Domain
    for row in rows:
        d = Domain.query.filter(Domain.id == row).scalar()
        d.delete()
    return True


def get_col_types():
    return [{'name': 'Text', 'type': 'text'},
            {'name': 'Email', 'type': 'email'},
            {'name': 'Checkbox', 'type': 'checkbox'},
            {'name': 'Date', 'type': 'calendar'},
            {'name': 'Numeric', 'type': 'numeric'},
            {'name': 'Phone Number', 'type': 'phone'},
            {'name': 'URL', 'type': 'url'},
            {'name': 'Currency', 'type': 'currency'},
            {'name': 'Percent', 'type': 'percent'}]


def format_column_name(col):
    return col.replace('_', ' ').title()


def print_traceback(e):
    traceback.print_tb(e.__traceback__)
    print(e)
