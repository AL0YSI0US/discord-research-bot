import json
from pathlib import Path
from discord_slash import cog_ext
from discord.ext import commands
from datetime import datetime
from database import *
from helpers import *
import discord
import logging
import asyncio

logger = logging.getLogger(__name__)

def has_been_curated_before(message) -> bool:
    """Checks whether or not a message has been curated before.

    :param message: Any message.
    :type message: Union[discord.Message]
    :return: Whether or not it has happened.
    :rtype: bool
    """
    document = Message.get(
        (where('channel_id') == message.channel.id) &
        (where('message_id') == message.id)
    )

    return document is not None and \
        document.status != Message.Status.VINTAGE

async def add_to_database(bot, document):
    anonymize = document.status == Message.Status.ANONYMOUS

    channel = await bot.fetch_channel(document.channel_id)
    message = await channel.fetch_message(document.message_id)

    inserted = {
        'content': message.content,
        'timestamp': (message.edited_at or message.created_at).isoformat(),
        'author_hash': user_to_hash(message.author.id),
        'curated_at': document.metadata['curated_at'].isoformat(),
        'curated_by': document.metadata['curated_by'],
        'requested_at': document.metadata['requested_at'].isoformat(),
        'requested_by': document.metadata['requested_by'],
        'fufilled_at': document.metadata['fulfilled_at'].isoformat()
    }

    if not anonymize:
        inserted['author'] = {
            'id': message.author.id,
            'name': message.author.name,
            'discriminator': message.author.discriminator
        }

    # Fetch all of the comments.
    inserted['comments'] = []
    for comment in document.comments:
        comment_channel = await bot.fetch_channel(comment['channel_id'])
        comment_msg = comment_channel.fetch_message(comment['message_id'])

        inserted['comments'].append({
            'timestamp': comment_msg.edited_at or comment_msg.created_at,
            'author': {
                'id': comment_msg.author.id,
                'name': comment_msg.author.name,
                'discriminator': comment_msg.author.discriminator
            },
            'content': comment_msg.content
        })

    # Read the contents of the file first.
    contents = []
    if Path(DATABASE_FNAME).exists():
        with open(DATABASE_FNAME, 'r') as file:
            contents = json.load(file)
    
    contents.append(inserted)
    with open(DATABASE_FNAME, 'w') as file:
        json.dump(contents, file, indent=4)
    
    logger.info('Written to database')


class CuratorCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # @commands.command()
    # @commands.check(is_admin)
    # async def export(self, ctx):
    #     """Gives the callee all of the curated data."""
    #     if ctx.guild:
    #         return await ctx.reply('This command must be run in DMs.')

    #     # Show that the command was successfully received.
    #     await ctx.message.add_reaction('👍')

    #     exported = []
    #     for document in db.handle.table(MESSAGES_TABLE_NAME):

    #         # Add all comments to this message.
    #         if 'comments' not in document:
    #             document['comments'] = []
            
    #         message = db.message(
    #             channel_id=document.get('original_cid'),
    #             message_id=document.get('original_mid')
    #         )

    #         for comment in message.comments:
    #             document['comments'].append(comment)
            
    #         # Add to resulting list.
    #         exported.append(document)
        
    #     # Make the folder if it does not exist.
    #     folder = Path('exports')
    #     folder.mkdir(exist_ok=True)

    #     # Write to a file.
    #     filename = folder / f'{datetime.utcnow().isoformat()}.json'
    #     with open(filename, 'w') as file:
    #         json.dump(exported, file, indent=4)

    #     # Send to callee.
    #     with open(filename, 'r') as file:
    #         await ctx.send(file=discord.File(file))

    @commands.command()
    @commands.check(is_admin)
    async def quickconfig(self, ctx, pending: discord.TextChannel,
        approved: discord.TextChannel, guild: discord.Guild=None):
        """Sets a guild's pending and approved channels. The guild defaults to
        the guild you send the command in."""
        if guild is None:
            guild = ctx.guild
        
        document = Guild.get(doc_id=guild.id)
        if document is None:
            document = Guild(doc_id=guild.id)
        
        document.pending_channel_id = pending.id
        document.approved_channel_id = approved.id
        document.save()

        await ctx.reply('Done!')

    @commands.command()
    @commands.check(is_admin)
    async def viewconfig(self, ctx, guild: discord.Guild=None):
        """Checks a guild's pending and approved channels. The guild defaults to
        the guild you send the command in."""
        if guild is None:
            guild = ctx.guild

        document = Guild.get(doc_id=guild.id)

        pending = None if document is None else \
            await self.bot.fetch_channel(document.pending_channel_id)
        approved = None if document is None else \
            await self.bot.fetch_channel(document.approved_channel_id)
        
        pending_text = 'Not configured' if pending is None else \
            f'**{pending.guild.name}** - #{pending.name}'
        approved_text = 'Not configured' if approved is None else \
            f'**{approved.guild.name}** - #{approved.name}'
        
        lines = []
        lines.append(f'The pending channel for **{ctx.guild.name}** is:'
            f' {pending_text}')
        lines.append(f'The approved channel for **{ctx.guild.name} is:'
            f' {approved_text}')
        text = '\n'.join(lines)

        await ctx.reply(text)

    @commands.Cog.listener()
    async def on_message(self, message):
        # Do not proceed if it is not a reply.
        if message.reference is None:
            return
            
        # Do not proceed if it is our own reply.
        if message.author == self.bot.user:
            return logger.debug('Ignoring our own reply %s/%s',
                message.channel.id, message.id)
        
        alternate = Alternate.get(
            (where('alternate_channel_id') == message.reference.channel_id) & \
            (where('alternate_message_id') == message.reference.message_id) & \
            (where('type') == Alternate.Type.COMMENTABLE)
        )
        
        # Do not proceed if the reference is not commentable.
        if alternate is None:
            return logger.debug('Message %s/%s is not commentable',
                alternate.channel_id, alternate.message_id)
        
        # Add comment to original message.
        original = Message.get(
            (where('channel_id') == alternate.original_channel_id) & \
            (where('message_id') == alternate.original_message_id)
        )

        original.comments.append({
            'channel_id': message.channel.id,
            'message_id': message.id
        })
        original.save()

        await message.add_reaction('👍')

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        # Do not proceed if it was our own reaction.
        reactor = await self.bot.fetch_user(payload.user_id)
        if reactor == self.bot.user:
            return logger.debug('Ignoring own reaction on %s/%s',
                payload.channel_id, payload.message_id)

        channel = await self.bot.fetch_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)

        # Delegate to other method.
        await self.on_emoji_add(message, str(payload.emoji), reactor)
    
    async def on_emoji_add(self, message, emoji, reactor):
        # Check if it is the required emoji to curate this message.
        if emoji != get_emoji(self.bot, message):
            return logger.debug('Emoji %s not correct for %s/%s, returning',
                emoji, message.channel.id, message.id)
        
        # Ensure that we are not in direct messages.
        if not message.guild:
            return logger.debug('%s/%s is not from a server, returning',
                message.channel.id, message.id)
        
        # Ensure message has not been curated before.
        if has_been_curated_before(message):
            return logger.debug('%s/%s has already been curated before',
                message.channel.id, message.id)
        
        await self.start_curation(message, reactor)

    async def start_curation(self, message, reactor):
        config = Guild.get(doc_id=message.guild.id)

        # Get the pending channel for this server.
        if config is None:
            return logger.debug('Pending channel for %s is not set',
                message.guild.id)
        
        channel = await self.bot.fetch_channel(config.pending_channel_id)

        # Avoid curating this message again and add extra metadata.
        original = Message(
            # Not using `get`, overwrite is fine if there is a collision.
            channel_id=message.channel.id,
            message_id=message.id,
            status=Message.Status.CURATED,
            metadata={
                'curated_by': {
                    'id': reactor.id,
                    'name': reactor.name,
                    'discriminator': reactor.discriminator
                },
                'curated_at': datetime.utcnow()
            }
        ).save()

        # Send to the pending channel.
        pending = await channel.send(
            embed=message_to_embed(message),
            components=[make_pending_action_row()]
        )

        # Tie original and pending messages together.
        Alternate(
            alternate_channel_id=pending.channel.id,
            alternate_message_id=pending.id,
            type=Alternate.Type.PENDING,
            original_channel_id=original.channel_id,
            original_message_id=original.message_id
        ).save()
    
    @cog_ext.cog_component(components=[
        REQUEST_PERMISSION_CUSTOM_ID, 
        REQUEST_WITH_COMMENT_CUSTOM_ID
    ])
    async def on_request_permission_pressed(self, ctx):
        # Defer immediately to avoid 'This interaction failed'.
        await ctx.defer(ignore=True)

        # Get the original message.
        alternate = Alternate.get(
            (where('alternate_channel_id') == ctx.origin_message.channel.id) & \
            (where('alternate_message_id') == ctx.origin_message.id) & \
            (where('type') == Alternate.Type.PENDING)
        )

        # Ensure no one can click this button twice.
        original = Message.get(
            (where('channel_id') == alternate.original_channel_id) & \
            (where('message_id') == alternate.original_message_id)
        )

        if original.status != Message.Status.CURATED:
            return logger.error('Observer %s tried to request permission'
                ' twice for %s/%s', ctx.author.id, original.channel_id,
                original.message_id)
        
        original.status = Message.Status.REQUESTED
        original.metadata['requested_by'] = {
            'id': ctx.author.id,
            'name': ctx.author.name,
            'discriminator': ctx.author.discriminator
        }

        original.metadata['requested_at'] = datetime.utcnow()
        original.save()

        # Turn the document into a message.
        channel = await self.bot.fetch_channel(original.channel_id)
        original = await channel.fetch_message(original.message_id)

        # Disable the buttons and make the actual request.
        await disable_pending_action_row(ctx.origin_message)
        await self.send_permission_request(original)

        # Send commentable message to observer if they want.
        if ctx.custom_id == REQUEST_WITH_COMMENT_CUSTOM_ID:
            await self.send_comment_hook(ctx.author, original)

    async def send_comment_hook(self, user, original):
        """Sends a message to `user` which quotes `original` and explains that,
        if `user` replies, a comment will be added to `original` in database."""
        embed = message_to_embed(original)
        add_commentable_message(embed)
        hook = await user.send(embed=embed)

        # Register the message that we just sent as commentable.
        original_model = Message.get(
            (where('channel_id') == original.channel.id) & \
            (where('message_id') == original.id)
        )

        Alternate(
            alternate_channel_id=hook.channel.id,
            alternate_message_id=hook.id,
            type=Alternate.Type.COMMENTABLE,
            original_channel_id=original_model.channel_id,
            original_message_id=original_model.message_id
        ).save()

    async def send_permission_request(self, message):
        # Send an introduction if we haven't met this person yet.
        author = User.get(doc_id=message.author.id)
        if author is None or not author.have_met:
            await send_introduction(message.author, message.guild)
            author.have_met = True
            author.save()
        
        # Send the actual request.
        embed = message_to_embed(message)
        add_consent_message(embed)
        request = await message.author.send(
            embed=embed,
            components=[make_request_action_row()]
        )

        # Tie original and request messages together.
        Alternate(
            alternate_channel_id=request.channel.id,
            alternate_message_id=request.id,
            type=Alternate.Type.REQUEST,
            original_channel_id=message.channel.id,
            original_message_id=message.id
        ).save()

    @cog_ext.cog_component(components=[
        YES_CUSTOM_ID,
        YES_ANONYMOUSLY_CUSTOM_ID,
        NO_CUSTOM_ID
    ])
    async def on_permission_request_fulfilled(self, ctx):
        # Avoids 'This interaction failed'.
        await ctx.defer(ignore=True)

        # Get the original message.
        alternate = Alternate.get(
            (where('alternate_channel_id') == ctx.origin_message.channel.id) & \
            (where('alternate_message_id') == ctx.origin_message.id) & \
            (where('type') == Alternate.Type.REQUEST)
        )

        # Ensure button cannot be pressed twice.
        original = Message.get(
            (where('channel_id') == alternate.original_channel_id) & \
            (where('message_id') == alternate.original_message_id)
        )

        if original.status >= Message.Status.APPROVED:

            # Only works because `MessageStatus.APPROVED` is integer-wise
            # less than or equal to the others.
            return logger.error('User %s tried to fulfill twice for %s/%s',
                ctx.author.id, original.channel_id, original.message_id)
        
        # Add extra metadata.
        original.metadata['fulfilled_at'] = datetime.utcnow()

        channel = await self.bot.fetch_channel(original.channel_id)
        message = await channel.fetch_message(original.message_id)

        # Set the appropriate status and add to database.
        if ctx.custom_id == YES_CUSTOM_ID:
            original.status = Message.Status.APPROVED
            await add_to_database(self.bot, original)
        elif ctx.custom_id == YES_ANONYMOUSLY_CUSTOM_ID:
            original.status = Message.Status.ANONYMOUS
            await add_to_database(self.bot, original)
        else: # User denied permission.
            original.status = Message.Status.DENIED
        
        # Save the document.
        original.save()

        # Disable the buttons and convert to an actual message.
        await disable_request_action_row(ctx.origin_message)
        original = message # From earlier.

        # Send thanks based on response.
        if ctx.custom_id == YES_CUSTOM_ID or \
            ctx.custom_id == YES_ANONYMOUSLY_CUSTOM_ID:
            await send_thanks(original.author, True, original.guild)
        else: # User denied permission.
            await send_thanks(original.author, False, original.guild)
        
        # Delete the pending message.
        model = Alternate.get(
            (where('original_channel_id') == original.channel.id) & \
            (where('original_message_id') == original.id) & \
            (where('type') == Alternate.Type.PENDING)
        )

        channel = await self.bot.fetch_channel(model.alternate_channel_id)
        pending = await channel.fetch_message(model.alternate_message_id)
        await pending.delete()

        # Also, clear it from the database.
        model.delete()

        # Quit early if user denied permission.
        if ctx.custom_id == NO_CUSTOM_ID:
            return logger.info('User %s denied permission for %s/%s',
                ctx.author.id, original.channel.id, original.id)
        
        # Send to the approved channel.
        anonymous = (ctx.custom_id == YES_ANONYMOUSLY_CUSTOM_ID)
        await self.send_to_approved(original, anonymous=anonymous)
    
    async def send_to_approved(self, message, anonymous=False):
        config = Guild.get(doc_id=message.guild.id)

        # Get the approved channel for the originating guild.
        if config is None:
            return logger.error('Approved channel for %s is not set',
                message.guild.id)
        
        channel = await self.bot.fetch_channel(config.approved_channel_id)
        
        # Send to the approved channel.
        embed = message_to_embed(message, anonymize=anonymous)
        add_commentable_message(embed)
        approved = await channel.send(embed=embed)

        # Tie original and approved messages together and make it commentable.
        Alternate(
            alternate_channel_id=approved.channel.id,
            alternate_message_id=approved.id,
            type=Alternate.Type.APPROVED,
            original_channel_id=message.channel.id,
            original_message_id=message.id
        ).save()

        Alternate(
            alternate_channel_id=approved.channel.id,
            alternate_message_id=approved.id,
            type=Alternate.Type.COMMENTABLE,
            original_channel_id=message.channel.id,
            original_message_id=message.id
        ).save()

def setup(bot):
    cog = CuratorCog(bot)
    bot.add_cog(cog)
