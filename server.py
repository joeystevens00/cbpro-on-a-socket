import asyncio
import cbpro
from types import GeneratorType
from typing import Callable


class OptionMap:
    def __init__(self, opts):
        self.m = dict()
        for i, o in enumerate(opts):
            self.m[i] = o

    def __str__(self):
        return '\n'.join([f'{i})  {o}' for i, o in self.m.items()]) + "\n"

    def __dict__(self):
        return self.m

    def __getitem__(self, item):
        return self.m.__getitem__(item)


class CoinBaseLatestPrice:
    """I'm not much of a protocol, but I'll tell you the price of Bitcoin."""

    def __init__(self):
        self.public_client = cbpro.PublicClient()
        self.tickers = self.public_client.get_products()
        self.methods = OptionMap([m for m in dir(self.public_client) if m.startswith('get_product_')])
        self.clients = {}
        self.ticker_map = OptionMap(self.ticker_ids())
        self.ticker_options = str(self.ticker_map).encode('utf-8')

        # Each state is processed in this order:
        # process arg and set state -> ingest function -> cb function -> transition function or set state literal
        # cb is executed if the state still matches after the ingest function

        self.states = {
            'prompt_ticker_id': {
                'arg': 'l',
                'cb': lambda message, client: self.welcome_pick_a_ticker(client),
                'transition': 'get_ticker_id',
            },
            'get_ticker_id': {
                'ingest': lambda message, client: self.ingest_message(message, client),
            },
            'make_api_request': {
                'ingest': lambda message, client: self.ingest_message(message, client),
                'cb': lambda message, client: self.make_api_request(message, client),
            },
            'prompt_api_method_name': {
                'arg': 'm',
                'cb': lambda _, client: self.select_a_method(client),
                'transition': 'get_api_method_name',
            },
            'get_api_method_name': {
                'ingest': lambda message, client: self.pick_a_method(message, client),
            }

        }

    def connection_made(self, transport):
        self.transport = transport

    def ticker_ids(self):
        ticker_ids = [t['id'] for t in self.tickers]
        ticker_ids.sort()
        return ticker_ids

    def pick_a_method(self, message, client):

        def set_client_method(method):
            print("SETTING METHOD:", method, "for client", client)
            client['method'] = method
            if client.get('ticker'):
                client['state'] = 'make_api_request'
            else:
                self.welcome_pick_a_ticker(client)
                client['state'] = 'get_ticker_id'


        def invalid_input():
            self.transport.sendto(b'What do you want? PICK\n', client['addr'])
            self.select_a_method(client['addr'])

        if not message or not len(message):
            invalid_input()
        elif message.isdigit():
            set_client_method(self.methods[int(message)])
        elif message in self.methods:
            set_client_method(message)
        else:
            invalid_input()

    def ingest_message(self, message, client):
        print("INGEST", message)
        if message.isdigit():
            client['ticker'] = self.ticker_map[int(message)]
            client['state'] = 'make_api_request'
        else:
            if '-' in message:
                client['ticker'] = message
                client['state'] = 'make_api_request'
            else:
                if client['state'] == 'get_ticker_id':
                    self.transport.sendto(b'Pick a ticker or beat it!', client['addr'])

    def make_api_request(self, message, client):
        method = client.get('method') or self.methods[0]
        data = self.public_client.__getattribute__(method)(product_id=client['ticker'])
        if isinstance(data, GeneratorType):
            data = next(data)
        response = f"({method}) TICKER {client['ticker']} (l to list all, m to select method, select any freely)\n {repr(data)}"
        self.transport.sendto(response.encode('utf-8'), client['addr'])

    def welcome_pick_a_ticker(self, client):
        self.transport.sendto(b'Hello friend, pick a ticker:\n', client['addr'])
        self.transport.sendto(self.ticker_options, client['addr'])

    def select_a_method(self, client):
        self.transport.sendto(f'Pick a method:\n{str(self.methods)}'.encode('utf-8'), client['addr'])

    def connection_lost(self, *args):
        print('CONNECTION LOST', args)

    def datagram_received(self, data, addr):
        message = data.decode()
        if message.endswith('\n'):
            message = message[0:len(message) - 1]
        if not self.clients.get(addr):
            self.clients[addr] = {'state': 'prompt_ticker_id', 'addr': addr}
        print(message, self.clients[addr])

        client = self.clients[addr]

        # Process args and set state
        for state, config in self.states.items():
            if message.lower() == config.get('arg'):
                print("SETTING STATE", state)
                client['state'] = state

        for state, config in self.states.items():
            if client['state'] == state:
                # Call ingest function
                if config.get('ingest'):
                    print("CALLING INGEST", state)
                    config['ingest'](message, client)
                # State can change after the ingest function
                if client['state'] == state:
                    # Call CB function
                    if config.get('cb'):
                        print("CALLING CB", state)
                        config['cb'](message, client)
                if config.get('transition'):
                    transition = config['transition']
                    print("transition", transition)
                    # Set state to transition literal value
                    if isinstance(transition, (int, str)):
                        client['state'] = transition
                    # Call transition function
                    elif isinstance(transition, Callable):
                        transition(message, client)
                    else:
                        raise ValueError(f"Invalid transition {transition}")
                    break

def main():
    loop = asyncio.get_event_loop()
    print("Starting server")

    # One protocol instance will be created to serve all client requests
    listen = loop.create_datagram_endpoint(
        CoinBaseLatestPrice, local_addr=('0.0.0.0', 12000))
    transport, protocol = loop.run_until_complete(listen)

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass

    transport.close()
    loop.close()


if __name__ == "__main__":
    main()
