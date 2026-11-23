---
name: windows-network
description: Сети и администрирование Windows — диагностика интернета, IP/DNS, порты, команды PowerShell и cmd, Windows Server (AD, DHCP, DNS, GPO), Cisco Packet Tracer, подсети. Используй для учёбы по сетям и для проблем с сетью на ПК.
triggers: интернет, сеть, wifi, wi-fi, роутер, ip, dns, пинг, ping, порт, подсеть, маска, vlan, cisco, packet tracer, windows server, active directory, dhcp
---
# Сети и Windows

## Нет интернета / тормозит — по порядку, только чтение
1. ipconfig /all → есть ли IP (не 169.254.x.x), шлюз, DNS.
2. ping <шлюз> → ping 1.1.1.1 → ping google.com
   (шлюз нет = кабель/Wi-Fi; 1.1.1.1 есть, google нет = DNS; ничего нет = провайдер/роутер).
3. Test-NetConnection <хост> -Port 443 · tracert <хост> · Get-NetAdapter · netsh wlan show interfaces (сигнал).
4. Чинить (ipconfig /flushdns, сброс адаптера, netsh winsock reset) — только объяснив и после «да».
   В роутер не заходи и пароли не вводи — дай инструкцию.

## Порты и процессы
Get-NetTCPConnection -State Listen | sort LocalPort · кто держит порт: Get-Process -Id (Get-NetTCPConnection -LocalPort N).OwningProcess

## Подсети (часто на контрольных)
Маска /n → хостов 2^(32−n) − 2. Пример 192.168.10.0/26: маска 255.255.255.192, шаг 64,
сети .0 .64 .128 .192, широковещательный = следующая сеть − 1. Решай таблицей: сеть, первый, последний, broadcast.

## Windows Server (учёба)
AD DS: Install-WindowsFeature AD-Domain-Services -IncludeManagementTools → Install-ADDSForest.
DHCP: Add-DhcpServerv4Scope; DNS: Add-DnsServerPrimaryZone; пользователи: New-ADUser; GPO: gpmc.msc.
Объясняй, что делает каждая команда, и предупреждай, что это для лабораторной машины, не для его ПК.

## Packet Tracer / Cisco IOS
enable → conf t → hostname → interface g0/0 → ip address A M → no shutdown; VLAN: vlan N, switchport access vlan N;
проверка: show ip int brief, show vlan brief, show running-config. Ошибки ищи по порядку: кабель → IP/маска → шлюз → VLAN.
