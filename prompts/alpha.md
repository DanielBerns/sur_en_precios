# Brainstorming "Sur en Precios"

I want to brainstorm the design of a system with the following components:
1. A webscraper of the website https://datos.produccion.gob.ar/dataset/sepa-precios
2. A private control and communication website for the webscraper, with auth credentials and very few users.
3. A processor for transforming the daily updates downloaded by the webscraper in a consolidated database, with the goal of solving several queries about supermarket prices.
4. A public website where registered users can view the results of different queries about supermarket prices.

/grill-me about this subject. This is a very complex system, but I don't want to overengineering it.
