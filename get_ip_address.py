import requests

def get_ip():
    try:
        response = requests.get('https://api.ipify.org?format=json')
        response.raise_for_status()
        ip_info = response.json()
        return ip_info['ip']
    except requests.RequestException as e:
        print(f"Error fetching IP address: {e}")
        return None

ip_address = get_ip()
if ip_address:
    print(f"Your IP address is: {ip_address}")
else:
    print("Failed to get IP address.")
