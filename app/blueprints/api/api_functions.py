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
import mysql.connector
from alembic import op
from datetime import datetime
from collections import defaultdict
from app.extensions import db
from sqlalchemy import exists, and_, or_, inspect, asc, func
from flask import current_app, jsonify, make_response
from importlib import import_module
from app.blueprints.page.date import get_dt_string, is_datetime, format_datetime, get_utc_date_today
from flask_login import current_user


# Get from database **********************************
def get_table(d):
    try:
        conn = db.create_engine(current_app.config.get('SQLALCHEMY_DATABASE_URI'), connect_args={'connect_timeout': 300}, pool_timeout=300, pool_recycle=3600)
        m = db.MetaData()
        m.reflect(conn)
        t = None
        for table in m.tables.values():
            if table.name == d:
                t = table

        db.session.close()
        return t
    except Exception as e:
        print_traceback(e)
        return None


def get_tables(user_id):
    tables = list()

    from app.blueprints.api.models.tables import Table
    ts = Table.query.filter(Table.user_id == user_id).all()

    for t in ts:
        tables.append({'name': t.name, 'id': t.table_id})

    return tables


def get_rows(t, columns, limit=None):
    rows = list()

    # Get the rows and the columns
    domains = db.session.query(t).limit(limit).all() if limit is not None else db.session.query(t).all()
    if columns is None: return domains

    for domain in domains:
        # False is the first item in each row, which is the select checkbox
        data = [False]

        for column in [x for x in columns if x.name not in hidden_columns()]:

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


def get_columns(d):

    try:
        cols = [{'title': ' ', 'type': 'checkbox', 'width': 50}]

        # Get the columns
        columns = d.columns
        for column in columns:
            width = 250
            options = {}
            data = {}
            type = str(column.type).lower().strip()

            # Format column types
            if 'varchar' in type:
                type = 'text'

            if 'boolean' in type or 'tinyint' in type:
                type = 'checkbox'
                width = 150

            if 'integer' in type:
                type = 'numeric'

            # Format date columns
            if 'date' in type:
                type = 'calendar'
                options.update({'today': True, 'format': 'MM/DD/YYYY'})

            # Make created and updated columns, as well as record id readonly
            if column.name == 'created_on' or column.name == 'updated_on' or column.name == 'record_id':
                width = 150
                data.update({'readOnly': True})

            # Update the column's data
            data.update({'title': format_column_name(column.name), 'type': type, 'options': options, 'width': width})

            # Don't add hidden columns
            if column.name not in hidden_columns():
                # Create a dictionary for each column name and its type
                cols.append(data)

        return cols, columns
    except Exception as e:
        print_traceback(e)
        return None, None
    except Error as r:
        print_traceback(r)
        return None, None


# Update Table *******************************************
def create_table(table_name, user_id, linked=None):
    table_name = generate_full_table_name(table_name)

    mydb = mysql.connector.connect(
        host=current_app.config.get('SQLALCHEMY_HOST'),
        user=current_app.config.get('SQLALCHEMY_USER'),
        passwd=current_app.config.get('SQLALCHEMY_PASSWORD'),
        database=current_app.config.get('SQLALCHEMY_DATABASE')
    )
    mycursor = mydb.cursor()

    try:
        # If this table is linked to another
        if linked is not None:
            sql = ("CREATE TABLE `%s` ("
                   "`id` int(11) NOT NULL AUTO_INCREMENT,"
                   "`record_id` varchar(255) DEFAULT NULL,"
                   "`created_on` date DEFAULT NULL,"
                   "`updated_on` date DEFAULT NULL,"
                   "`user_id` int(11) DEFAULT '%s',"
                   "`table_id` varchar(255) DEFAULT NULL,"
                   "`linked_id` varchar(255) DEFAULT '%s',"
                   "KEY ix_%s_user_id (`user_id`), "
                   "KEY ix_%s_linked_id (`linked_id`), "
                   "PRIMARY KEY (`id`), "
                   "CONSTRAINT `%s_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE CASCADE, "
                   "CONSTRAINT `%s_ibfk_3` FOREIGN KEY (`linked_id`) REFERENCES `%s` (`table_id`) ON DELETE CASCADE ON UPDATE CASCADE"
                   ") ENGINE=InnoDB DEFAULT CHARSET=utf8 "
                   "AUTO_INCREMENT=1 ;" % (table_name, user_id, linked, table_name, table_name, table_name, table_name, linked))
        else:
            sql = ("CREATE TABLE `%s` ("
                   "`id` int(11) NOT NULL AUTO_INCREMENT,"
                   "`record_id` varchar(255) DEFAULT NULL,"
                   "`created_on` date DEFAULT NULL,"
                   "`updated_on` date DEFAULT NULL,"
                   "`user_id` int(11) DEFAULT '%s',"
                   "`table_id` varchar(255) DEFAULT '%s',"
                   "`linked_id` varchar(255) DEFAULT NULL,"
                   "KEY ix_%s_user_id (`user_id`), "
                   "PRIMARY KEY (`id`), "
                   "CONSTRAINT `%s_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE CASCADE "
                   ") ENGINE=InnoDB DEFAULT CHARSET=utf8 "
                   "AUTO_INCREMENT=1 ;" % (table_name, user_id, table_name, table_name, table_name))

        # Create the table
        mycursor.execute(sql)
        mycursor.close()
        mydb.close()

        # add it to the "tables" table
        if save_table(table_name, user_id):
            return table_name
        return None
    except Exception as e:
        print_traceback(e)
        return None


def save_table(table_name, user_id):
    try:
        if get_table(table_name) is not None:
            from app.blueprints.api.models.tables import Table

            t = Table()
            t.user_id = user_id
            t.name, t.table_id = split_table_name(table_name)
            t.save()

            return True
        return False
    except Exception as e:
        print_traceback(e)
        return False


def split_table_name(table_name):
    name, table_id = re.split('_tbl_', table_name)
    return name, 'tbl_' + table_id


def create_record(table_name):

    if table_name is None: return

    try:
        record_id = generate_record_id(get_table(table_name))
        today = get_utc_date_today()
        print(today)
        mydb = mysql.connector.connect(
            host=current_app.config.get('SQLALCHEMY_HOST'),
            user=current_app.config.get('SQLALCHEMY_USER'),
            passwd=current_app.config.get('SQLALCHEMY_PASSWORD'),
            database=current_app.config.get('SQLALCHEMY_DATABASE')
        )
        mycursor = mydb.cursor()

        sql = ("INSERT INTO `%s` (`created_on`, `updated_on`, `record_id`, `user_id`, `table_id`, `linked_id`) VALUES ('%s', '%s', '%s', '%s', '%s', NULL) " % (table_name, today, today, record_id, current_user.id, table_name))
        mycursor.execute(sql)

        mydb.commit()
        mycursor.close()
        mydb.close()
    except Exception as e:
        print_traceback(e)


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
def generate_id(size=7, chars=string.digits):
    # Generate a random 7-character user id
    id = int(''.join(random.choice(chars) for _ in range(size)))

    from app.blueprints.api.models.domains import Domain

    # Check to make sure there isn't already that id in the database
    if not db.session.query(exists().where(Domain.id == id)).scalar():
        return id
    else:
        generate_id()


def generate_full_table_name(table_name):
    table_name = table_name.lower().replace(' ', '_')
    id = generate_table_id()
    return table_name + '_' + id


def generate_table_id(size=16):
    # Generate a random 12-character table id
    chars = string.digits + string.ascii_lowercase
    id = 'tbl_' + ''.join(random.choice(chars) for _ in range(size))

    from app.blueprints.api.models.tables import Table

    # Check to make sure there isn't already that id in the database
    if not db.session.query(exists().where(Table.table_id == id)).scalar():
        return id
    else:
        generate_table_id()


def generate_record_id(table, size=16):
    # Generate a random 7-character record id
    chars = string.digits + string.ascii_lowercase
    id = 'rec_' + ''.join(random.choice(chars) for _ in range(size))

    # Check to make sure there isn't already that id in the database
    if not db.session.query(exists().where(table.c.id == id)).scalar():
        return id
    else:
        generate_id()


def count_rows(table_name):

    if table_name is None: return 0

    # conn = db.create_engine(current_app.config.get('SQLALCHEMY_DATABASE_URI'), connect_args={'connect_timeout': 300}, pool_timeout=300, pool_recycle=3600)
    mydb = mysql.connector.connect(
        host=current_app.config.get('SQLALCHEMY_HOST'),
        user=current_app.config.get('SQLALCHEMY_USER'),
        passwd=current_app.config.get('SQLALCHEMY_PASSWORD'),
        database=current_app.config.get('SQLALCHEMY_DATABASE')
    )
    mycursor = mydb.cursor()
    mycursor.execute('select * from %s' % table_name)
    mycursor.fetchall()
    count = mycursor.rowcount

    mydb.commit()
    mycursor.close()
    mydb.close()
    return count


def get_limit(lim):
    lim = None if lim == 0 else lim
    return lim


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
    if col == 'linked_id': col = 'linked to'
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


def hidden_columns():
    return ['id', 'table_id', 'user_id']


def cont():
    pass
