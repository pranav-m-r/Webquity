# Webquity

### Video Demo:  [YouTube](https://youtu.be/_c462mDdCjw)

### Description:

Webquity is an online stock exchange simulator built using Flask (Python) with a backend based on HTML, CSS & JavaScript. It uses an SQLite database to store user data and transaction history. It makes use of SQL queries safe from SQL injection and also employs user login security features by setting limitations on the username and password. The app also uses various types of alerts to let the user know about any important actions, errors or invalid entries, and also provides confirmation of transactions to the user to provide a better user experience. Now, let me give you a brief explanation on each of the routes available on the web application.

#### 1. Portfolio:
The user dashboard (user portfolio) provides the user with an overview on their current holdings and account statistics. The user can view their account balance, the amount withdrawn from the account till date, et cetera, and also buy and sell stocks they currently hold right from their portfolio.

![Webquity-Portfolio](https://github.com/pranav-m-r/Webquity/assets/148135964/fab82f03-3c80-4f56-ab30-53c80224c554)

#### 2. Login/Register:
These two separate routes let the user login to their account or create a new one securely with restrictions on the selection of username and password.

![Webquity-Register](https://github.com/pranav-m-r/Webquity/assets/148135964/7751370e-d02f-4f70-826d-4d7988eecf8d)

#### 3. Search:
This route is used to get a quote or stock summary of any stock symbol at that instant along with stock trends in the form of charts.

![Webquity-Search-Stocks](https://github.com/pranav-m-r/Webquity/assets/148135964/5be6d46d-6550-4a7a-af2e-051e51becb9d)

#### 4. Buy/Sell:
This route lets the user buy new stocks or sell existing holdings by providing the stock symbol as an input. They are available as separate webpages in the application and are also accessible via the portfolio page. A successful transaction is followed up by a transaction summary.

![Webquity-Buy-Stocks](https://github.com/pranav-m-r/Webquity/assets/148135964/cb80881b-577a-48a3-a64f-710108dd214c)

#### 5. History:
This route allows the user to view a summary of all the previous transactions on their account. The various stocks bought and sold since the account was created are shown in a tabular format along with the transaction dates and times.

![Webquity-Transaction-History](https://github.com/pranav-m-r/Webquity/assets/148135964/b07ce215-f5b6-4c37-9bac-51ea10260faf)

#### 6. Deposit/Withdraw:
These routed allow the user to add cash to their accounts and withdraw cash from the same. These statistics are shown on the portfolio and used to calculate the net or overall profit.

![Webquity-Deposit-Cash](https://github.com/pranav-m-r/Webquity/assets/148135964/06398e6d-5bd4-4255-bdcc-ffae662db5de)

#### 7. Transaction Review:
This page gives the user a summary and confirmation of any transaction (buying or selling of shares, depositing or withdrawing of cash, et cetera) which has been successfully completed on their account. Any errors are shown to the user in the form of an alert, in which case the user will be redirected back to the original page instead of this page.

![Webquity-Transaction-Review](https://github.com/pranav-m-r/Webquity/assets/148135964/dc9718fa-cab7-4f83-bccc-20aa3871e2b7)

#### 8. Change Password:
This route allows the user to change their account's login password, subject to the same restrictions as when the account was created.

![Webquity-Password](https://github.com/pranav-m-r/Webquity/assets/148135964/33abc6ac-983b-4a30-8a54-b5c524c26295)

### Credits:

#### 1. [CS50](https://cs50.harvard.edu/x/2024/) & [EdX](https://www.edx.org/):
I want to thank CS50 for the wonderful learning experience it has provided me. I would specially thank Prof. David Malan whose energy and way of teaching ensures that we are listening in with all our attention and never getting bored. This project is built on the base provided by my favourite CS50 problem set, Finance, so credits to the team for that. Thanks to edX for helping me register for these classes all the way from India and for giving me a hassle-free learning experience.
#### 2. [Yahoo Finance](https://finance.yahoo.com/):
I would like to thank Yahoo for their Finance API which proved to be very useful acting as the base to the application's real-time stock data.
#### 3. [StockCharts](https://stockcharts.com/):
I would also like to thank StockCharts for their wonderful, well, stock charts (XD). They added a crucial feature to the app and also helped enhance its user interface.
#### 4. [Flaticon](https://www.flaticon.com/):
Finally, a thanks to Flaticon for the website's favicon, which I found interesting since it conveys all the importance aspects of stock trading without seeming too generic.
