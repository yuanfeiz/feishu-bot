# Feishu Bot
## Install
```
pip install feishu_bot
```
## Getting Started
```
from feishu_bot import FeishuBot

bot = FeishuBot('your_app_id', 'your_app_secret')
await bot.send_text('test')
```

By default, the message will be sent to all groups where the bot joins. However the optional `groups` argument can be set to specify the recipient group(s).

```
image_key = await bot.upload_image('https://picsum.photos/200/300')
await bot.send_image(image_key, groups='oc_foo')

# If you'd like to send this image to multiple groups
await bot.send_image(image_key, groups=['oc_bar', ''oc_foo'])
```
Call `get_groups` manually to get all the groups visible to the bot:
```
await bot.get_groups()
```

## Features
- Automatically token management
- Cache embeded