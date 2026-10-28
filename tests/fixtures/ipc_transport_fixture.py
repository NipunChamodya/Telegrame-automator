"""Synthetic stdio peer for Swift transport tests. No Telethon or application data."""
import asyncio
import json
import os
import sys


async def main():
    reader = asyncio.StreamReader()
    await asyncio.get_running_loop().connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer)
    tasks = {}
    def write(value):
        sys.stdout.write(json.dumps(value, ensure_ascii=False) + '\n')
        sys.stdout.flush()
    async def handle(request):
        request_id = request['id']
        method = request['method']
        if method == 'wait':
            await asyncio.sleep(30)
        if method == 'progress':
            write({'event': 'progress', 'request_id': request_id, 'data': {'index': 1}})
        if method == 'malformed':
            sys.stdout.write('not a JSON frame\n')
            sys.stdout.flush()
            return
        if method == 'close_input':
            write({'id': request_id, 'ok': True, 'result': {}})
            os.close(sys.stdin.fileno())
            await asyncio.sleep(30)
            return
        if method == 'close_output':
            os.close(sys.stdout.fileno())
            await asyncio.sleep(30)
            return
        write({'id': request_id, 'ok': True, 'result': request.get('params', {})})
    while line := await reader.readline():
        request = json.loads(line)
        if request['method'] == 'shutdown':
            write({'id': request['id'], 'ok': True, 'result': {'shutting_down': True}})
            break
        if request['method'] == 'cancel':
            target = tasks.get(request['params']['request_id'])
            if target:
                target.cancel()
            write({'id': request['id'], 'ok': True, 'result': {}})
            continue
        tasks[request['id']] = asyncio.create_task(handle(request))
    for task in tasks.values():
        task.cancel()
    await asyncio.gather(*tasks.values(), return_exceptions=True)


if __name__ == '__main__':
    asyncio.run(main())
