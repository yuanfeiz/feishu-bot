from io import BytesIO
from .log import logger
from cachetools import TTLCache, keys
from asyncache import cached
import asyncio
import json
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed, before_sleep_log
from .errors import RequestError, TokenExpiredError
from datetime import timedelta
from aiohttp import ClientSession, ClientResponse, MultipartWriter, FormData


class FeishuBot:
    def __init__(self,
                 app_id,
                 app_secret,
                 base_url='https://open.feishu.cn/open-apis',
                 token_ttl=None):
        self.app_id = app_id
        self.app_secret = app_secret
        self.base_url = base_url
        self.token_cache = TTLCache(1, token_ttl or timedelta(hours=1).seconds)

    @retry(stop=stop_after_attempt(3),
           wait=wait_fixed(1),
           retry=retry_if_exception_type(TokenExpiredError))
    async def request(self, method, endpoint, *args, **kwargs):
        url = f'{self.base_url}{endpoint}'
        no_auth = kwargs.pop('no_auth', False)
        if no_auth:
            # skip auth, for getting token itself
            headers = kwargs.pop('headers', {})
        else:
            # attach the token by default
            token = await self.get_access_token()
            headers = {
                'Authorization': f'Bearer {token}',
                **kwargs.pop('headers', {})
            }

        async with ClientSession() as session:
            async with session.request(method,
                                       url,
                                       *args,
                                       headers=headers,
                                       **kwargs) as resp:
                resp_json = await resp.json()

        code = resp_json['code']
        msg = resp_json['msg']

        if code > 0:
            # documentation: https://open.feishu.cn/document/ukTMukTMukTM/ugjM14COyUjL4ITN
            if code == 99991663:
                # tenant access token error
                # invalidate the cache and retry again
                self.token_cache.clear()
                raise TokenExpiredError(code, msg)
            raise RequestError(code, msg)

        logger.debug(f'requested: url={url} response={resp_json}')

        return resp_json

    async def get(self, endpoint, *args, **kwargs):
        return await self.request('GET', endpoint, *args, **kwargs)

    async def post(self, endpoint, *args, **kwargs):
        return await self.request('POST', endpoint, *args, **kwargs)

    # refresh every 1 hour
    async def get_access_token(self):
        cached_token = self.token_cache.get(keys.hashkey(self))

        if cached_token:
            return cached_token

        url = f'/auth/v3/app_access_token/internal/'
        resp = await self.post(url,
                               no_auth=True,
                               json={
                                   'app_id': self.app_id,
                                   'app_secret': self.app_secret
                               })
        token = resp['tenant_access_token']
        self.token_cache[keys.hashkey(self)] = token

        return token

    @cached(TTLCache(32, timedelta(days=1).seconds))
    async def get_user_detail(self, open_id: str):
        url = f'/contact/v1/user/batch_get'
        resp = await self.get(url, params={'open_ids': open_id})
        return resp['data']['user_infos'][0]

    # refresh every 5 minutes
    @cached(TTLCache(1, timedelta(minutes=5).seconds))
    async def get_groups(self):
        resp = await self.get('/chat/v4/list')
        return resp['data']['groups']

    async def update_group_name(self, chat_id: str, new_name: str):
        """
        Update group name
        """
        resp = await self.post('/chat/v4/update/',
                               json={
                                   'chat_id': chat_id,
                                   'name': new_name
                               })

        return resp

    async def send_to_groups(self,
                             msg_type,
                             content=None,
                             card=None,
                             **kwargs):
        groups = kwargs.get('groups')
        if groups is None:
            # by default send the message to all groups
            detailed_groups = await self.get_groups()
            groups = [g['chat_id'] for g in detailed_groups]
        elif isinstance(groups, str):
            # single chat_id
            groups = [groups]
        
        tasks = []
        for g in groups:
            payload = {
                'chat_id': g,
                'msg_type': msg_type,
            }
            if card is not None:
                payload['card'] = card
                payload['update_multi'] = kwargs['is_shared']
            else:
                payload['content'] = content
            tasks.append(self.post('/message/v4/send/', json=payload))

        results = await asyncio.gather(*tasks)

        logger.debug(f'Sent {msg_type}={content} to {[g for g in groups]}')

        return results

    async def send_text(self, text: str, groups=None):
        """
        Send plain text
        """
        return await self.send_to_groups('text', {'text': text}, groups=groups)

    async def upload_image(self, url):
        """
        Upload image of the given url
        """
        async with ClientSession() as session:
            img_resp = await session.get(url)
            b = await img_resp.content.read()

        resp = await self.post('/image/v4/put/',
                               data={
                                   'image_type': 'message',
                                   'image': b
                               })

        image_key = resp['data']['image_key']
        logger.debug(f'uploaded image: url={url} image_key={image_key}')

        return image_key

    async def send_image(self, image_url, groups=None):
        """
        Send image
        """
        image_key = await self.upload_image(image_url)
        return await self.send_to_groups('image', {'image_key': image_key}, groups=groups)

    async def send_post(self, title, content, groups=None):
        """
        Send post(image+text)
        documentation: https://open.feishu.cn/document/ukTMukTMukTM/uMDMxEjLzATMx4yMwETM
        """
        return await self.send_to_groups(
            'post', {'post': {
                'zh_cn': {
                    'title': title,
                    'content': content
                }
            }}, groups=groups)

    async def send_card(self, card, is_shared=False, groups=None):
        """
        Send interactive card
        documentation: https://open.feishu.cn/document/ukTMukTMukTM/ugTNwUjL4UDM14CO1ATN 
        """
        assert isinstance(card, dict)
        return await self.send_to_groups('interactive',
                                            card=card,
                                            is_shared=is_shared, groups=groups)
