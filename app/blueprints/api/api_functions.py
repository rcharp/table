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
from app.blueprints.page.date import get_dt_string, is_datetime, format_datetime, get_today_date_string
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


def get_records(table, columns, limit=None):
    rows = list()

    # Get the records
    records = db.session.query(table).limit(limit).all() if limit is not None else db.session.query(table).all()
    if columns is None: return domains

    # If there are no records, add a blank one to start.
    if len(records) == 0:
        pass #add_blank_row(rows, columns, table)

    for record in records:
        # False is the first item in each row, which is the select checkbox
        data = [False]

        for column in [x for x in columns if x.name not in hidden_columns()]:

            # Get the column's value for the row
            e = getattr(record, column.name, cont())

            # Format any dates
            if is_datetime(e):
                e = format_datetime(e)

            # Add the column's value to the list
            data.append(e)
        rows.append(data)

    # Add a blank row to the end of the list.
    # This will serve as the "New Row" row at the end of the table
    add_blank_row(rows, columns)
    return rows


def get_columns(d):
    try:
        cols = [{'title': ' ', 'type': 'checkbox', 'width': 50}]

        # Get the columns
        columns = [x for x in d.columns if x.name not in hidden_columns()]
        for column in columns:
            width = 250
            options = {}
            source = list()
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

            # Get linked column type
            if column.name == 'linked_id':
                type = 'dropdown'
                source = ['Ferrari', 'Lamborghini', 'MacLaren', 'Bentley']

            # Make created and updated columns, as well as record id, readonly
            if column.name == 'created_on' or column.name == 'updated_on':
                width = 150
                data.update({'readOnly': True})

            if column.name == 'record_id':
                width = 200
                data.update({'readOnly': True})

            # Get the column's title
            title = get_column_title(column.name)

            # Update the column's data
            data.update({'title': title, 'type': type, 'options': options, 'source': source, 'width': width})

            # Don't add hidden columns
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
        # if linked is not None:
        #     sql = ("CREATE TABLE `%s` ("
        #            "`id` int(11) NOT NULL AUTO_INCREMENT,"
        #            "`record_id` varchar(255) DEFAULT NULL UNIQUE,"
        #            "`created_on` date DEFAULT NULL,"
        #            "`updated_on` date DEFAULT NULL,"
        #            "`user_id` int(11) DEFAULT '%s',"
        #            "`table_id` varchar(255) DEFAULT NULL,"
        #            "`linked_id` varchar(255) DEFAULT '%s',"
        #            "KEY ix_%s_user_id (`user_id`), "
        #            "KEY ix_%s_linked_id (`linked_id`), "
        #            "PRIMARY KEY (`id`), "
        #            "CONSTRAINT `%s_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE CASCADE, "
        #            "CONSTRAINT `%s_ibfk_3` FOREIGN KEY (`linked_id`) REFERENCES `%s` (`table_id`) ON DELETE CASCADE ON UPDATE CASCADE"
        #            ""
        #            ") ENGINE=InnoDB DEFAULT CHARSET=utf8 "
        #            "AUTO_INCREMENT=1 ;" % (table_name, user_id, linked, table_name, table_name, table_name, table_name, linked))
        # else:
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
               "CONSTRAINT `%s_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE CASCADE, "
               "CONSTRAINT `%s_iu_1` UNIQUE (`record_id`)"
               ") ENGINE=InnoDB DEFAULT CHARSET=utf8 "
               "AUTO_INCREMENT=1 ;" % (table_name, user_id, table_name, table_name, table_name, table_name))

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


def create_record(table_name, record_id):
    if table_name is None: return

    try:
        # record_id = generate_record_id(get_table(table_name))
        today = get_today_date_string()
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
        return True
    except Exception as e:
        print_traceback(e)
        return False
    except Error as r:
        print_traceback(r)
        return False


def delete_record(table_name, row):
    if table_name is None: return False

    try:
        mydb = mysql.connector.connect(
            host=current_app.config.get('SQLALCHEMY_HOST'),
            user=current_app.config.get('SQLALCHEMY_USER'),
            passwd=current_app.config.get('SQLALCHEMY_PASSWORD'),
            database=current_app.config.get('SQLALCHEMY_DATABASE')
        )
        mycursor = mydb.cursor()

        sql = ("DELETE FROM %s WHERE `record_id` = '%s'" % (table_name, row))
        mycursor.execute(sql)

        mydb.commit()
        mycursor.close()
        mydb.close()

        return True
    except Exception as e:
        print_traceback(e)
        return False
    except Error as r:
        print_traceback(r)
        return False


def update_record(table_name, col, val, row):
    if table_name is None: return False
    col = get_column_name(col)

    try:
        mydb = mysql.connector.connect(
            host=current_app.config.get('SQLALCHEMY_HOST'),
            user=current_app.config.get('SQLALCHEMY_USER'),
            passwd=current_app.config.get('SQLALCHEMY_PASSWORD'),
            database=current_app.config.get('SQLALCHEMY_DATABASE')
        )
        mycursor = mydb.cursor()

        sql = ("UPDATE %s SET %s = '%s' WHERE `record_id` = '%s'" % (table_name, col, val, row))
        mycursor.execute(sql)

        mydb.commit()
        mycursor.close()
        mydb.close()

        return True
    except Exception as e:
        print_traceback(e)
        return False
    except Error as r:
        print_traceback(r)
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
        old = get_column_name(old)

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


def delete_rows(table_name, rows):
    results = list()
    for row in rows:
        result = delete_record(table_name, row)
        results.append(result)
    return results


def delete_column(rows):
    from app.blueprints.api.models.domains import Domain
    for row in rows:
        d = Domain.query.filter(Domain.id == row).scalar()
        d.delete()
    return True


def add_blank_row(rows, columns, table=None):
    data = [False]

    if table is not None:
        for column in columns:
            if column.name == 'created_on' or column.name == 'updated_on':
                data.append(get_today_date_string())
            elif column.name == 'record_id':
                data.append(generate_record_id(table))
            else:
                data.append(None)
        rows.append(data)
    else:
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

    try:
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
    except Exception as e:
        return -1
    except Error as r:
        return -1


def get_limit(lim):
    lim = None if lim == 0 else lim
    return lim


def get_col_types():
    return [{'name': 'Text', 'type': 'text', 'icon': "fa fa-file-text-o"},
            {'name': 'Email', 'type': 'email', 'icon': "si si-envelope-letter"},
            {'name': 'Checkbox', 'type': 'checkbox', 'icon': "fa fa-check-square-o"},
            {'name': 'Date', 'type': 'calendar', 'icon': "fa fa-calendar-check-o"},
            {'name': 'Numeric', 'type': 'numeric', 'icon': "fa fa-hashtag"},
            {'name': 'Phone Number', 'type': 'phone', 'icon': "fa fa-phone"},
            {'name': 'URL', 'type': 'url', 'icon': "si si-globe"},
            {'name': 'Currency', 'type': 'currency', 'icon': "fa fa-dollar"},
            {'name': 'Percent', 'type': 'percent', 'icon': "fa fa-percent"},
            {'name': 'Linked', 'type': 'dropdown', 'icon': "fa fa-external-link"}]


def get_default_column_names():
    cols = {'id': 'Id',
            'created_on': 'Created On',
            'updated_on': 'Last Updated',
            'table_id': 'Table Id',
            'record_id': 'Record Id',
            'linked_id': 'Linked To'
            }
    return cols


def get_column_title(name):
    names = get_default_column_names()

    for k, v in names.items():
        if name == k:
            return names[name]
    return name.replace('_', ' ').title()


def get_column_name(title):
    titles = get_default_column_names()

    for k, v in titles.items():
        if title == v:
            return k
    return title.lower().replace(' ','_')


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


def split_table_name(table_name):
    name, table_id = re.split('_tbl_', table_name)
    return name, 'tbl_' + table_id


def hidden_columns():
    return ['id', 'table_id', 'user_id']


def cont():
    pass


# Used to populate the db's record ids
def pop():
    mydb = mysql.connector.connect(
        host=current_app.config.get('SQLALCHEMY_HOST'),
        user=current_app.config.get('SQLALCHEMY_USER'),
        passwd=current_app.config.get('SQLALCHEMY_PASSWORD'),
        database=current_app.config.get('SQLALCHEMY_DATABASE')
    )
    mycursor = mydb.cursor()

    table = get_table('domains_tbl_domains')
    for x in range(165, 284):
        y = int(str(x) + str(1))
        rec = generate_record_id(table)

        sql = ("UPDATE %s SET %s = '%s' WHERE `id` = '%s'" % ('domains_tbl_domains', 'record_id', rec, y))

        mycursor.execute(sql)

        mydb.commit()
    mycursor.close()
    mydb.close()
