from flask import flash
import requests
import json
from app.blueprints.page.date import get_creation_date
from celery.result import AsyncResult


def test():
    return