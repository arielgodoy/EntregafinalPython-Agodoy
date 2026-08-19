import requests

url = 'https://palena.sii.cl/DTEWS/CrSeed.jws'
payloads = {
    'simple_ser': '<?xml version="1.0" encoding="UTF-8"?><soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ser="http://DefaultNamespace"><soapenv:Body><ser:getSeed/></soapenv:Body></soapenv:Envelope>',
    'rpc_encoded': '<?xml version="1.0" encoding="UTF-8"?><soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:soapenc="http://schemas.xmlsoap.org/soap/encoding/" xmlns:impl="http://DefaultNamespace"><soapenv:Body><impl:getSeed soapenv:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"/></soapenv:Body></soapenv:Envelope>',
    'xsd_soap': '<?xml version="1.0" encoding="UTF-8"?><soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ser="http://DefaultNamespace" xmlns:xsd="http://www.w3.org/2001/XMLSchema"><soapenv:Body><ser:getSeed/></soapenv:Body></soapenv:Envelope>',
}
for name, body in payloads.items():
    print('===', name, '===')
    for action in ['', 'getSeed', '"getSeed"']:
        headers = {'Content-Type': 'text/xml; charset=utf-8'}
        if action:
            headers['SOAPAction'] = action
        try:
            r = requests.post(url, data=body.encode('utf-8'), headers=headers, timeout=45)
            print('action=', repr(action), 'status=', r.status_code, 'ctype=', r.headers.get('Content-Type'))
            print(r.text[:600].replace('\n', ' ')[:600])
        except Exception as e:
            print('action=', repr(action), 'ERR', type(e).__name__, e)
    print()
