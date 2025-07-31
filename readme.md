python version 3.12.10
LM studio version 0.3.15 build 11
cloudflared.exe
everytime opens:
#1
 run 

 LB.py
 
 and run

#the webhook part has been automated.
 cloudflared tunnel --url http://localhost:5000 

in console

and get the  

Your quick Tunnel has been created! Visit it at (it may take some time to be reachable):  |
2025-07-15T09:29:58Z INF |  https://xml-picnic-judgment-cause.trycloudflare.com  

and then put the link to

https://developers.line.biz/console/channel/2006995867/messaging-api

#2
open up LLM studio, make 

text embedding model 
answering model 

running in said order.

then test via line.

#to add file into database:
i used jsonl to save all my data into combine.jsonl.
tools are in adding data.
run factory to make pdf to jsonl with page and title.
run glue to glue

updated it to prepare_kb.py