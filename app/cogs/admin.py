from discord.ext import commands
from database import *
import discord

class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    @commands.is_owner()
    async def bootstrap(self, ctx):
        """Makes the owner of the bot an admin."""
        document = User.get(doc_id=ctx.author.id)
        if document is None:
            document = User(doc_id=ctx.author.id)
        
        document.is_admin = True
        document.save()

        await ctx.message.add_reaction('👍')
    
    @commands.command()
    @commands.check(is_admin)
    async def admin(self, ctx, user: discord.User=None):
        """Makes a user an admin or demotes them if they are an admin."""
        document = User.get(doc_id=ctx.author.id)
        if document is None:
            document = User(doc_id=ctx.author.id)
        
        document.is_admin = not document.is_admin
        document.save()
        
        await ctx.message.add_reaction('👍')

def setup(bot):
    cog = AdminCog(bot)
    bot.add_cog(cog)
