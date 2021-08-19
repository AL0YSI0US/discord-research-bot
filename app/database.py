from datetime import datetime
from enum import IntEnum
from tinyengine import *


@register_model
class User(Model):
    is_admin = Field(bool, default=lambda: False)
    have_met = Field(bool, default=lambda: False)


@register_model
class Message(Model):
    channel_id = Field(int, required=True)
    message_id = Field(int, required=True, unique_with=['channel_id'])

    class Status(IntEnum):
        VINTAGE = 0
        CURATED = 1
        REQUESTED = 2
        APPROVED = 3
        ANONYMOUS = 4
        DENIED = 5

    def validate_status(field):
        if not isinstance(field, (int, Message.Status)):
            raise FieldValidationError(field)

    status = Field(Status, required=True, validator=validate_status)
    comments = Field(list) # Empty list by default.
    metadata = Field(dict) # Empty dictionary by default.


@register_model
class Alternate(Model):
    alternate_channel_id = Field(int, required=True)
    alternate_message_id = Field(int, required=True)
    
    class Type(IntEnum):
        PENDING = 0
        REQUEST = 1
        APPROVED = 2
        COMMENTABLE = 3
    
    def validate_type(field):
        if not isinstance(field, (int, Alternate.Type)):
            raise FieldValidationError(field)

    type = Field(Type, required=True, validator=validate_type, unique_with=[
        'alternate_channel_id', 'alternate_message_id'])
    original_channel_id = Field(int, required=True)
    original_message_id = Field(int, required=True)


@register_model
class Channel(Model):
    group = Field(str, required=True)


@register_model
class Guild(Model):
    pending_channel_id = Field(int, required=True)
    approved_channel_id = Field(int, required=True)
    bridge_channel_id = Field(int)


def is_admin(ctx):
    # Checks if the given `discord.Context` is from an (bot) admin user.
    user = User.get(doc_id=ctx.author.id)
    return False if user is None else user.is_admin
