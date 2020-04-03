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
def generate_id(size=12, chars=string.digits):
    # Generate a random 12-character user id
    new_id = int(''.join(random.choice(chars) for _ in range(size)))

    return new_id


def print_traceback(e):
    traceback.print_tb(e.__traceback__)
    print(e)


def update_row(id, val, col):
    try:

        # Get the corresponding item from the table
        from app.blueprints.api.models.domains import Domain
        d = Domain.query.filter(Domain.id == id).scalar()

        # If the value has been changed, then update the table
        if getattr(d, col) != val:
            setattr(d, col, val)
            d.save()

            # return jsonify({"success": 200})
            return True
        # return jsonify({"error": 500})
        return False
    except Excpetion as e:
        print_traceback(e)
        # return jsonify({"error": 500})
        return False


def get_col_types():
    return [{'name': 'Text', 'type': 'text'},
             {'name': 'Email', 'type': 'email'},
             {'name': 'Boolean', 'type': 'boolean'},
             {'name': 'Date', 'type': 'date'},
             {'name': 'Phone Number', 'type': 'phone'},
             {'name': 'URL', 'type': 'url'},
             {'name': 'Currency', 'type': 'currency'},
             {'name': 'Percent', 'type': 'percent'}]