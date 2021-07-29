from discord.ext import commands
from discord.message import Message
from discord.raw_models import RawReactionActionEvent
from discord_slash import cog_ext
from discord_slash.context import ComponentContext, SlashContext
from discord.utils import get
from discord_slash.model import ButtonStyle
from discord_slash.utils.manage_components import create_actionrow, create_button
from config import config, perms
from utils import message_to_embed
from tinydb import TinyDB
import discord
import sys
import re

EMOJI = '🔭'
ANONYMOUS = 'anonymous'

def make_permission_action_row(disabled=False):
    return create_actionrow(
        create_button(
            style=ButtonStyle.green,
            label='Yes',
            # emoji='👍',
            custom_id='accept',
            disabled=disabled
        ),
        create_button(
            style=ButtonStyle.blue,
            label='Yes, anonymously',
            # emoji='🕵️',
            custom_id='anonymous',
            disabled=disabled
        ),
        create_button(
            style=ButtonStyle.red,
            label='No',
            # emoji='👎',
            custom_id='decline',
            disabled=disabled
        ),
        create_button(
            style=ButtonStyle.URL,
            label='Join our server',
            # emoji='🗺️',
            url='https://discord.com/'
        )
    )

async def get_emojicount(message: Message, guild: discord.Guild):
    # Get's number of EMOJIs on message by curators.
    count = 0
    reaction = get(message.reactions, emoji=EMOJI)
    async for user in reaction.users():
        member = await guild.fetch_member(user.id)
        if get(member.roles, name='Curator'):
            count += 1
    return count

def make_database_entry(user, content, timestamp, guild, channel, emojicount):
    # Returns something readily insertable into the database.
    entry = {
        'content': content,
        'timestamp': timestamp.isoformat(),
        'guild': {
            '_id': guild.id,
            'name': guild.name
        },
        'channel': {
            '_id': channel.id,
            'name': channel.name
        },
        'emojicount': emojicount
    }

    # Handle the anonymous case.
    if user:
        entry['author'] = {
            '_id': user.id,
            'name': user.name
        }
    
    return entry

class CuratorCog(commands.Cog):
    '''Enables curation of interesting messages.'''

    def __init__(self, bot):
        self.bot = bot
    
    @cog_ext.cog_subcommand(
        base='set',
        name='pending',
        description='Set the pending messages channel.',
        guild_ids=config['guild_ids'],
        base_permissions=perms,
        base_default_permission=False
    )
    async def _set_pending(self, ctx: SlashContext):
        # Use the current channel's ID.
        config['pending_id'] = ctx.channel_id
        mention = ctx.channel.mention
        await ctx.send(f'Pending messages will now go to {mention}.')

    @cog_ext.cog_subcommand(
        base='set',
        name='approved',
        description='Set the approved messages channel.',
        guild_ids=config['guild_ids'],
        base_permissions=perms,
        base_default_permission=False
    )
    async def _set_approved(self, ctx: SlashContext):
        # Use the current channel's ID.
        config['approved_id'] = ctx.channel_id
        mention = ctx.channel.mention
        await ctx.send(f'Approved messages will now go to {mention}.')
    
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: RawReactionActionEvent):
        channel = await self.bot.get_or_fetch_channel(payload.channel_id)
        if not channel.guild:
            return # We are in a DM.
        
        reactor = await channel.guild.fetch_member(payload.user_id)
        if not get(reactor.roles, name='Curator'):
            return # Ignore non-curators.

        message = await channel.fetch_message(payload.message_id)
        count = await get_emojicount(message, channel.guild)
        if str(payload.emoji) == EMOJI and count == 1:
            await self.on_message_reacted(message)
    
    async def on_message_reacted(self, message):
        if 'pending_id' not in config:
            return sys.stderr.write('\'pending_id\' is not set!')

        embed = message_to_embed(message)

        row = create_actionrow(
            create_button(
                style=ButtonStyle.blue,
                label='Request permission',
                custom_id=f'ask-{message.author.id}'
            )
        )

        channel = await self.bot.get_or_fetch_channel(config['pending_id'])
        await channel.send(embed=embed, components=[row])
    
    @commands.Cog.listener()
    async def on_component(self, ctx: ComponentContext):
        if ctx.custom_id.startswith('ask-'):
            await ctx.origin_message.delete()

            # Recover author of original message.
            askee_id = int(ctx.custom_id[4:])
            askee = await self.bot.get_or_fetch_user(askee_id)

            embed = ctx.origin_message.embeds[0]
            row = make_permission_action_row()

            embed.add_field(
                name='Consent Message',
                value='''We're asking for permission to quote you in our research.
• Yes you may quote my post and attribute it to my Discord Handle.
• You may quote my post anonymously, do not use my Discord Handle or any other identifying information.
• No, you may not quote my post in your research.
Thanks for helping us understand the future of governance!'''
            )

            await askee.send(embed=embed, components=[row])
        
        if ctx.custom_id == 'accept':
            embed = ctx.origin_message.embeds[0]
            embed.remove_field(0) # Remove consent message.

            # Disable buttons.
            row = make_permission_action_row(disabled=True)
            await ctx.edit_origin(components=[row])

            await self.on_message_approved(embed)

        if ctx.custom_id == ANONYMOUS:
            embed = ctx.origin_message.embeds[0]
            embed.remove_field(0) # Remove consent message.

            # Anonymize.
            embed.set_author(
                name=ANONYMOUS,
                url='', # Remove message link.
                icon_url='https://i.imgur.com/qbkZFWO.png'
            )

            # Disable buttons.
            row = make_permission_action_row(disabled=True)
            await ctx.edit_origin(components=[row])

            await self.on_message_approved(embed)

        if ctx.custom_id == 'decline':
            # Disable buttons.
            row = make_permission_action_row(disabled=True)
            await ctx.edit_origin(components=[row])

        await ctx.send('Done!', delete_after=5)

    async def on_message_approved(self, embed):
        # Send to approved channel.
        channel = await self.bot.get_or_fetch_channel(config['approved_id'])

        if embed.author.name == 'anonymous':
            embed.set_author(
                name=embed.author.name, 
                url='', # Remove message link.
                icon_url=embed.author.avatar_url
            )
        
        await channel.send(embed=embed)

        # Add to database.
        pattern = '^.*/([0-9]+)/([0-9]+)/([0-9]+)$'
        results = re.search(pattern, embed.author.url)
        
        guild_id = results.group(1)
        channel_id = results.group(2)
        message_id = results.group(3)

        # Send to observatory channel in guild.
        if 'repeats' in config and \
            str(guild_id) in config['repeats']:
            channel_id = config['repeats'][str(guild_id)]
            observe = await self.bot.get_or_fetch_channel(channel_id)
            await observe.send(embed=embed)

        # guild = await self.bot.get_or_fetch_guild(guild_id)
        channel = await self.bot.get_or_fetch_channel(channel_id)
        message = await channel.fetch_message(message_id)

        entry = make_database_entry(
            user=None if embed.author.name == 'anonymous' \
                else message.author,
            content=message.content,
            timestamp=message.edited_at or \
                message.created_at,
            guild=message.guild,
            channel=message.channel,
            emojicount=await get_emojicount(message, channel.guild)
        )

        # Write to disk.
        name = 'messages.json' if 'db' not in config else config['db']
        print(f'  Adding message to {name}')
        d = TinyDB(name, indent=4)
        d.insert(entry)

def setup(bot):
    bot.add_cog(CuratorCog(bot))