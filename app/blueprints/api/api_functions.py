import re
import sys
import time
import pytz
import boto3
import string
import random
import requests
import traceback
import psycopg2
from alembic import op
from datetime import datetime
from collections import defaultdict
from app.extensions import db
from sqlalchemy import exists, and_, or_, inspect, asc, func
from flask import current_app, jsonify, make_response
from importlib import import_module
from app.blueprints.page.date import get_dt_string, is_datetime, format_datetime
from flask_login import current_user


# Get from database **********************************
def get_table(d):
    conn = db.create_engine(current_app.config.get('SQLALCHEMY_DATABASE_URI'), connect_args={'connect_timeout': 300}, pool_timeout=300, pool_recycle=3600)
    m = db.MetaData()
    m.reflect(conn)
    t = None
    for table in m.tables.values():
        if table.name == d:
            t = table

    db.session.close()
    return t


def get_tables():
    table_name = 'domains'
    table = get_table(table_name)

    return [{'name': table_name, 'count': count_rows(table)}]


def get_rows(t, columns, limit=None):
    rows = list()

    # Get the rows and the columns
    domains = db.session.query(t).limit(limit).all() if limit is not None else db.session.query(t).all()
    if columns is None: return domains

    for domain in domains:
        # False is the first item in each row, which is the select checkbox
        data = [False]

        for column in columns:

            # Get the column's value for the row
            e = getattr(domain, column.name, cont())

            # Format any dates
            if is_datetime(e):
                e = format_datetime(e)

            # Add the column's value to the list
            data.append(e)
        rows.append(data)

    # Add a blank row to the list
    add_blank_row(rows, columns)
    return rows


def cont():
    pass


def get_columns(d):

    cols = [{'title': ' ', 'type': 'checkbox', 'width': 50}]

    # Get the columns
    columns = d.columns
    for column in columns:
        width = 250
        options = {}
        data = {}
        type = str(column.type).lower().strip()
        if 'varchar' in type: type = 'text'
        # Format boolean columns
        if 'boolean' in type or 'tinyint' in type:
            type = 'checkbox'
            width = 150

        if 'integer' in type:
            type = 'numeric'

        # Format date columns
        if 'date' in type:
            type = 'calendar'
            options.update({'today': True, 'format': 'MM/DD/YYYY'})

        # Make created and updated columns readonly
        if column.name == 'created_on' or column.name == 'updated_on' or column.name == 'id':
            width = 150
            data.update({'readOnly': True})

        # Update the column's data
        data.update({'title': format_column_name(column.name), 'type': type, 'options': options, 'width': width})

        # Create a dictionary for each column name and its type
        cols.append(data)

    return cols, columns


# Update Table *******************************************
def create_table(table_name, user_id):
    return


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


def add_column(table, column, type):
    try:
        type = format_type(type)
        user = current_app.config.get('SQLALCHEMY_USER')
        database = current_app.config.get('SQLALCHEMY_DATABASE')
        host = current_app.config.get('SQLALCHEMY_HOST')
        password = current_app.config.get('SQLALCHEMY_PASSWORD')

        conn = psycopg2.connect(host=host, database=database, user=user, password=password)

        cur = conn.cursor()
        cur.execute('ALTER TABLE %s ADD COLUMN %s %s' % (table, column, type))
        conn.commit()

        return True
    except Exception as e:
        print_traceback(e)
        return False


def update_column(table, name, old, type):
    try:
        old = col_title_to_name(old)

        access_key = current_app.config.get('AWS_ACCESS_KEY_ID')
        secret_key = current_app.config.get('AWS_ACCESS_KEY_SECRET')
        region = current_app.config.get('AWS_DEFAULT_REGION')
        partition_key = current_app.config.get('AWS_PARTITION_KEY')

        # Get the service resource.

        dynamodb = boto3.client('dynamodb', aws_access_key_id=access_key, aws_secret_access_key=secret_key, region_name=region)
        dynamodb.put_item(
            TableName='column_names',
            Item={
                partition_key:{"S": partition_key},
                table:
                    {"M":
                         {name:
                              {"M":
                                   {'column_name': {"S": name},
                                    'default_column_name': {"S": old}
                                    }
                               }
                          }
                     }
                }
            )

        return True
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


def add_blank_row(rows, columns):
    data = [False]
    for x in range(len(columns)):
        data.append(None)
    rows.append(data)


# Miscellaneous *************************************
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


def count_rows(d):
    return db.session.query(d).order_by(d.c.id).count()


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
    if col == 'id': col = 'record id'
    if col == 'updated_on': col = 'last updated'
    return col.replace('_', ' ').title()


def print_traceback(e):
    traceback.print_tb(e.__traceback__)
    print(e)


def format_type(type):
    if type == 'text' or type == 'email' or type == 'phone' or type == 'url' or type == 'currency' or type == 'percent':
        return 'text'
    if type == 'checkbox':
        return 'bool'
    if type == 'calendar':
        return 'date'
    if type == 'numeric':
        return 'int'


def col_title_to_name(col):
    return col.lower().replace(' ','_')
