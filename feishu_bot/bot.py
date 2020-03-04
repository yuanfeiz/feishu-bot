from io import BytesIO
from .log import logger
from cachetools import TTLCache, keys
from asyncache import cached
import asyncio
import json
from tenacity import retry, retry_if_exception_message, stop_after_attempt, wait_fixed, before_sleep_log
from .errors import RequestError, TokenExpiredError
from datetime import timedelta
from aiohttp import ClientSession, ClientResponse


class FeishuBot:
    def __init__(self,
                 app_id,
                 app_secret,
                 base_url='https://open.feishu.cn/open-apis'):
        self.app_id = app_id
        self.app_secret = app_secret
        self.base_url = base_url
        self.session = ClientSession()
        self.token_cache = TTLCache(1, timedelta(hours=1).seconds)

    @retry(stop=stop_after_attempt(3),
           wait=wait_fixed(1),
           retry=retry_if_exception_message(match='.*tenant_access_token.*'))
    async def request(self, method, endpoint, *args, **kwargs):
        url = f'{self.base_url}{endpoint}'
        no_auth = kwargs.pop('no_auth', False)
        if no_auth:
            # skip auth, for getting token itself
            headers = None
        else:
            # attach the token by default
            token = await self.get_access_token()
            headers = {'Authorization': f'Bearer {token}'}

        if 'json' in kwargs:
            logger.debug(f'payload: {json.dumps(kwargs["json"])}')

        resp_json = {}
        async with self.session.request(method, url, *args, headers=headers, **kwargs) as resp:
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

    async def send_to_groups(self,
                             msg_type,
                             content=None,
                             card=None,
                             **kwargs):
        groups = await self.get_groups()
        tasks = []
        for g in groups:
            payload = {
                'chat_id': g['chat_id'],
                'msg_type': msg_type,
            }
            if card is not None:
                payload['card'] = card
                payload['update_multi'] = kwargs['is_shared']
            else:
                payload['content'] = content
            tasks.append(self.post('/message/v4/send/', json=payload))

        results = await asyncio.gather(*tasks)

        return zip(groups, results)

    async def send_text(self, text: str):
        """
        Send plain text
        """
        results = await self.send_to_groups('text', {'text': text})
        logger.debug(f'Sent text={text} to {[g["name"] for g, _ in results]}')

    async def upload_image(self, url):
        """
        Upload image of the given url
        """
        img_resp: requests.Response = await self.session.get(url)
        resp = await self.post('/image/v4/put/',
                               data={'image_type': 'message'},
                               files={"image": img_resp.content},
                               stream=True)

        image_key = resp['data']['image_key']
        logger.debug(f'uploaded image: url={url} image_key={image_key}')

        return image_key

    async def send_image(self, image_url):
        """
        Send image
        """
        image_key = await self.upload_image(image_url)
        results = await self.send_to_groups('image', {'image_key': image_key})
        logger.debug(f'Sent image_url={image_url} to {[g["name"] for g, _ in results]}')

    async def send_post(self, title, content):
        """
        Send post(image+text)
        documentation: https://open.feishu.cn/document/ukTMukTMukTM/uMDMxEjLzATMx4yMwETM
        """
        results = await self.send_to_groups(
            'post', {'post': {
                'zh_cn': {
                    'title': title,
                    'content': content
                }
            }})
        logger.debug(f'Sent title={title} to {[g["name"] for g, _ in results]}')

    async def send_card(self, card, is_shared=False):
        """
        Send interactive card
        documentation: https://open.feishu.cn/document/ukTMukTMukTM/ugTNwUjL4UDM14CO1ATN 
        """
        assert isinstance(card, dict)
        results = await self.send_to_groups('interactive',
                                            card=card,
                                            is_shared=is_shared)
        logger.debug(f'Sent {card} to {[g["name"] for g, _ in results]}')
