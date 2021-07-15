from json.decoder import JSONDecodeError
from discord.embeds import EmptyEmbed
from discord.ext import commands
from discord import Guild, TextChannel, RawReactionActionEvent, Message, Member
from discord_slash.context import ComponentContext, SlashContext
from discord_slash.model import ButtonStyle
from discord_slash.utils import manage_components
from discord_slash import cog_ext
from discord_slash.utils.manage_commands import create_choice, create_option
from utils import user_to_color
from discord import utils
from datetime import datetime
import discord_slash
from main import slash, config
import os              # For manipulating files.
import discord
import json

GUILD_IDS  = [474736509472473088] # For slash commands.
DATA_FNAME = 'curation.json'      # Store all of our data in this file.
INIT_DATA  = {                    # What is initially stored & used.
    'guild_id':    474736509472473088,
    'pending_id':  862848348087517235,
    'approved_id': 862848298876141568
}

def to_embed(msg: discord.Message) -> discord.Embed:
    '''Turns a message into an embed(ded).'''
    embed = discord.Embed(
        description=msg.content,
        color=discord.Color.blue(),
        timestamp=msg.edited_at or msg.created_at
    )

    author: discord.User = msg.author

    embed.set_author(
        name=f"{author.display_name}#{author.discriminator}", 
        url=f"https://discord.com/users/{author.id}",
        icon_url=author.avatar_url
    )

    return embed

def build_permission_action_row(disabled=False):
    # Builds the action row for the permission message.
    return manage_components.create_actionrow(
        manage_components.create_button(
            custom_id='accept',
            style=ButtonStyle.green,
            disabled=disabled,
            label='yes'
        ),

        manage_components.create_button(
            custom_id='anon',
            style=ButtonStyle.gray,
            disabled=disabled,
            label='yes, but anonymously'
        ),

        manage_components.create_button(
            custom_id='decline',
            style=ButtonStyle.red,
            disabled=disabled,
            label='no'
        ),

        manage_components.create_button(
            style=ButtonStyle.URL,
            label='join our server',
            url='https://discord.com'
        )
        # manage_components.create_select(
        #     options=[
        #         create_select_option('yes', value='approve', emoji='👍'),
        #         create_select_option('yes, anonymously', value='anon', emoji='😎'),
        #         create_select_option('no',  value='decline', emoji='👎')
        #     ],
        #     placeholder='may we quote you in our research?',
        #     min_values=1,
        #     max_values=1
        # )
    )

class CuratorCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        print('Loaded', self.__class__.__name__)
        self.bot = bot

    @commands.command()
    @commands.has_role('Curator') # TODO: Make this work in DMs.
    async def curate(self, ctx: commands.Context, msg: discord.Message):
        # Manually start curation process.
        await self.begin_curation_process(msg)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: RawReactionActionEvent):
        # Triggered when a reaction is added to any message.
        ch: TextChannel = await self.bot.fetch_channel(payload.channel_id)

        # Ensure we are not in a DM.
        if not ch.guild:
            return

        message: Message = await ch.fetch_message(payload.message_id)
        reactor: Member = await ch.guild.fetch_member(payload.user_id)

        # Check for the appropriate emoji.
        if str(payload.emoji) == '🔭':
            # Check for the appropriate role.
            if utils.get(reactor.roles, name='Curator'): # TODO: Same as above.
                await self.begin_curation_process(message)

    async def begin_curation_process(self, msg: discord.Message):
        gd: Guild = await self.bot.fetch_guild(config['guild_id'])
        ch: TextChannel = await self.bot.fetch_channel(config['pending_id'])

        # Create "ask for permission" button.
        action_row = manage_components.create_actionrow(
            manage_components.create_button(
                custom_id=f'ask-{msg.author.id}',
                style=ButtonStyle.green,
                label='request permission'
            )
        )

        await ch.send(embed=to_embed(msg), components=[action_row])

    @commands.Cog.listener()
    async def on_component(self, ctx: ComponentContext):
        # Triggered on any component interaction.
        if 'ask-' in ctx.custom_id:
            embed: discord.Embed = ctx.origin_message.embeds[0]
            await ctx.origin_message.delete()

            # Ask user for permission.
            askee_id = int(ctx.custom_id[4:])
            askee: discord.User = await self.bot.fetch_user(askee_id)
            embed.set_footer(text='May we quote you in our research?')
            action_row = build_permission_action_row()
            await askee.send(embed=embed, components=[action_row, action_row, action_row])
        
        if 'accept' == ctx.custom_id:
            embed: discord.Embed = ctx.origin_message.embeds[0]
            action_row = build_permission_action_row(disabled=True)
            await ctx.origin_message.edit(components=[action_row])
            await self.message_approved(embed)
            
        if 'anon' == ctx.custom_id:
            embed: discord.Embed = ctx.origin_message.embeds[0]
            embed.set_author(
                name=f'anonymous sally', 
                url='',
                icon_url=''
            )

            # Propagate the anonymized message.
            action_row = build_permission_action_row(disabled=True)
            await ctx.origin_message.edit(components=[action_row])
            await self.message_approved(embed)
        
        if 'decline' == ctx.custom_id:
            action_row = build_permission_action_row(disabled=True)
            await ctx.origin_message.edit(components=[action_row])
            # Do nothing else, they have declined.
        
    async def message_approved(self, embed: discord.Embed):
        '''Called when a message should be sent to the approved channel.'''
        gd: Guild = await self.bot.fetch_guild(config['guild_id'])
        ch: TextChannel = await self.bot.fetch_channel(config['approved_id'])
        embed.set_footer(text=EmptyEmbed)
        await ch.send(embed=embed)

    @slash.slash(name='curate', guild_ids=GUILD_IDS)
    async def _curate(self, ctx: discord_slash.SlashContext):
        await ctx.send('pong!')

    '''Commands to manipulate pending and approved channels.'''

    @cog_ext.cog_subcommand(base='set', name='approved', guild_ids=GUILD_IDS)
    async def _set_approved(self, ctx: SlashContext):
        config['approved_id'] = ctx.channel.id
        await ctx.send('Done!')

    @cog_ext.cog_subcommand(base='set', name='pending', guild_ids=GUILD_IDS)
    async def _set_pending(self, ctx: SlashContext):
        config['pending_id'] = ctx.channel.id
        await ctx.send('Done!')
    
    # @cog_ext.cog_subcommand(base='set', name='reset', guild_ids=GUILD_IDS)
    # async def _set_reset(self, ctx: SlashContext):
    #     self.data = INIT_DATA
    #     self.sync()
    #     await ctx.send('Done!')


def setup(bot: commands.Bot):
    cog = CuratorCog(bot)
    bot.add_cog(cog)