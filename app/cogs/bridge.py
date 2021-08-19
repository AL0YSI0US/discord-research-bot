from helpers import message_to_embed
from typing import Generator, Optional
from discord.channel import TextChannel
from discord.ext import commands
from database import *
import discord

class BridgeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    @commands.check(is_admin)
    async def bridge(self, ctx, group: str=None, channel: TextChannel=None):
        """Sets a channel's group to `group`. If `group` is not provided, then
        the channel's group is cleared. Defaults to the channel where this
        command is being executed."""
        if channel is None:
            channel = ctx.channel

        if group is not None:
            document = Channel(doc_id=ctx.channel.id)
            document.group = group
            document.save()

            channels = self.get_channels_in_group(group)
            await ctx.reply(f'{ctx.channel.mention} is now connected to'
                f' {len(channels)} other channels in the group **{group}**.')

        else: # Delete group.
            document = Channel.get(doc_id=ctx.channel.id)
            if document is not None:
                
                document.delete()
                await ctx.reply(f'{ctx.channel.mention} is no longer connected'
                    ' to any other channel.')
            
            else: # Channel wasn't set in the first place.
                await ctx.reply(f'{ctx.channel.mention} is not a bridge.')


    @commands.Cog.listener()
    async def on_message(self, message):
        group = self.get_group(message.channel)
        if group is not None and message.author != self.bot.user:
            await self.replicate_in_group(message, group)
    
    async def replicate_in_group(self, message, group):
        embed = message_to_embed(message)
        embed.set_footer(text=f'{group} | {embed.footer.text}')

        for document in self.get_channels_in_group(group):
            channel = await self.bot.fetch_channel(document.doc_id)
            if channel != message.channel:
                await channel.send(embed=embed)

    def get_channels_in_group(self, group) -> Channel:
        return Channel.search(where('group') == group)
    
    def get_group(self, channel) -> Optional[str]:
        document = Channel.get(doc_id=channel.id)
        return None if document is None else document.group

def setup(bot):
    cog = BridgeCog(bot)
    bot.add_cog(cog)
