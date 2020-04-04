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
from sqlalchemy import exists, and_, or_, inspect
from flask import current_app, jsonify, make_response
from importlib import import_module
from app.blueprints.page.date import get_dt_string
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


def get_col_types():
    return [{'name': 'Text', 'type': 'text'},
             {'name': 'Email', 'type': 'email'},
             {'name': 'Boolean', 'type': 'boolean'},
             {'name': 'Date', 'type': 'date'},
             {'name': 'Phone Number', 'type': 'phone'},
             {'name': 'URL', 'type': 'url'},
             {'name': 'Currency', 'type': 'currency'},
             {'name': 'Percent', 'type': 'percent'}]


def print_traceback(e):
    traceback.print_tb(e.__traceback__)
    print(e)
