from typing import Optional

import pandas as pd
from numpy import random

from hummingbot.connector.utils import combine_to_hb_trading_pair
from hummingbot.core.data_type.common import TradeType
from hummingbot.core.data_type.order_candidate import OrderCandidate
from hummingbot.core.event.events import BuyOrderCompletedEvent, SellOrderCompletedEvent
from hummingbot.strategy.script_strategy_base import Decimal, OrderType, ScriptStrategyBase


class DirectionalExample(ScriptStrategyBase):
    """
    This example shows how to set up a simple directional strategy.
    """
    # Define exchange and assets to trade
    BASE = "BTC"
    QUOTE = "USDT"
    TRADING_PAIR = combine_to_hb_trading_pair(BASE, QUOTE)
    EXCHANGE = "binance_paper_trade"
    # Define markets to instruct Hummingbot to create connectors on the exchanges and markets you need
    markets = {EXCHANGE: {TRADING_PAIR}}
    # max quantity of tokens un base asset
    MAX_POSITION = 5
    # min quantity of tokens un base asset
    MIN_POSITION = 0
    # order size for each signal
    ORDER_SIZE = 0.1
    # min order size
    MIN_ORDER_SIZE = 0.02
    # The last time the strategy looks for a new signal
    TIME_BETWEEN_SIGNALS = 10
    # threshold to accept the signal and increase the position
    ENTRY_THRESHOLD = 0.6
    # threshold to reduce the position
    EXIT_THRESHOLD = 0.2
    # take profit in percentage (1% = 0.01)
    TAKE_PROFIT = 0.03
    # stop loss in percentage (1% = 0.01)
    STOP_LOSS = 0.01
    # last signal time to evaluate with time between signals
    last_signal_time = 0
    # signal stats
    # Index: Signal ID
    # Open Order ID: ID of the order that increase or decrease the position
    # Price: Execution price of the order
    # Amount: Excecution amount of the order
    # TP_price: Price * (1 + TAKE_PROFIT)
    # SL_price: Price * (1 - STOP_LOSS)
    # Status: [TP, SL, ACTIVE, CANCELED]
    # Close Order ID: Order ID that closes the position
    signals = pd.DataFrame(columns=["signal", "open_order_id", "price", "amount", "tp_price", "sl_price", "status", "close_order_id"])

    def on_tick(self):
        # Check active signals and review if it's necessary to create a take profit order or a stop loss market order
        self.update_active_signals()
        # Check if it is time to get a new signal
        if self.last_signal_time < (self.current_timestamp - self.TIME_BETWEEN_SIGNALS):
            self.last_signal_time = self.current_timestamp
            # get the signal
            signal = self.get_signal()
            signal_id = len(self.signals.index)
            # get current balance in base amount
            amount_base = self.get_balance(self.EXCHANGE, self.BASE)
            order_id = pd.NA
            if signal > self.ENTRY_THRESHOLD:
                self.logger().info(f"Signal > ENTRY THRESHOLD {self.ENTRY_THRESHOLD}")
                # check if the current balance is lower than the max position and
                # if the difference between max position and the balance is higher than the min order size
                if (amount_base < self.MAX_POSITION) and (self.MAX_POSITION - amount_base > self.MIN_ORDER_SIZE):
                    amount_to_buy = min(self.ORDER_SIZE, self.MAX_POSITION - float(amount_base))
                    order_id = self.adjust_and_place_order(
                        exchange=self.EXCHANGE,
                        trading_pair=self.TRADING_PAIR,
                        order_side=TradeType.BUY,
                        order_type=OrderType.MARKET,
                        is_maker=True,
                        amount=Decimal(amount_to_buy)
                    )
                    self.signals.loc[signal_id] = [signal, order_id, pd.NA, pd.NA, 0, 0, "ACTIVE", pd.NA]
            elif signal < self.EXIT_THRESHOLD:
                self.logger().info(f"Signal < EXIT THRESHOLD {self.EXIT_THRESHOLD} ==> TRY TO DECREASE POSITION")
                # check if the current balance is higher than the min position and
                # if the difference between min position and the balance is higher than the min order size
                if (amount_base > self.MIN_POSITION) and (amount_base - self.MIN_POSITION > self.MIN_ORDER_SIZE):
                    amount_to_sell = min(self.ORDER_SIZE, float(amount_base) - self.MIN_POSITION)
                    order_id = self.adjust_and_place_order(
                        exchange=self.EXCHANGE,
                        trading_pair=self.TRADING_PAIR,
                        order_side=TradeType.SELL,
                        order_type=OrderType.MARKET,
                        is_maker=True,
                        amount=Decimal(amount_to_sell)
                    )
                    # Close the active signal with the higher buy price
                    signal_to_remove = self.signals[self.signals["status"] == "ACTIVE"].argmax()
                    self.signals.loc[signal_to_remove, ["status", "close_order_id"]] = ["CANCELED", order_id]
                    self.signals.loc[signal_id] = [signal, order_id, pd.NA, pd.NA, 0, 0, pd.NA, pd.NA]
            else:
                self.signals.loc[signal_id] = [signal, order_id, pd.NA, pd.NA, pd.NA, pd.NA, pd.NA, pd.NA]

    @staticmethod
    def get_signal():
        return random.normal(loc=0.6, scale=0.25)

    def update_active_signals(self):
        active_signals = self.signals[self.signals["status"] == "ACTIVE"]
        best_ask = self.connectors[self.EXCHANGE].get_price(self.TRADING_PAIR, True)
        best_bid = self.connectors[self.EXCHANGE].get_price(self.TRADING_PAIR, False)
        for idx, signal in active_signals.iterrows():
            if signal["tp_price"] >= best_bid:
                order_id = self.buy(self.EXCHANGE, self.TRADING_PAIR, Decimal(self.ORDER_SIZE), OrderType.MARKET, best_bid)
                self.signals.loc[idx, ["status", "close_order_id"]] = ["TP", order_id]
            if signal["sl_price"] <= best_ask:
                order_id = self.sell(self.EXCHANGE, self.TRADING_PAIR, Decimal(self.ORDER_SIZE), OrderType.MARKET, best_ask)
                self.signals.loc[idx, ["status", "close_order_id"]] = ["SL", order_id]

    def format_status(self) -> str:
        """
        Returns status of the current strategy on user balances and current active orders. This function is called
        when status command is issued. Override this function to create custom status display output.
        """
        if not self.ready_to_trade:
            return "Market connectors are not ready."
        lines = []
        warning_lines = []
        warning_lines.extend(self.network_warning(self.get_market_trading_pair_tuples()))

        balance_df = self.get_balance_df()
        lines.extend(["", "  Balances:"] + ["    " + line for line in balance_df.to_string(index=False).split("\n")])

        try:
            df = self.active_orders_df()
            lines.extend(["", "  Orders:"] + ["    " + line for line in df.to_string(index=False).split("\n")])
        except ValueError:
            lines.extend(["", "  No active maker orders."])

        lines.extend(["", "  Signals:"] + ["    " + line for line in
                                           self.signals[["signal", "price", "tp_price", "sl_price", "status"]].to_string(index=False).split(
                                               "\n")])
        warning_lines.extend(self.balance_warning(self.get_market_trading_pair_tuples()))
        if len(warning_lines) > 0:
            lines.extend(["", "*** WARNINGS ***"] + warning_lines)
        return "\n".join(lines)

    def get_balance(self, exchange: str, asset: str):
        """
        Returns the balance of an asset in one exchange. Also returns 0 if the balance is negative
        """
        balance = max(self.connectors[exchange].get_balance(asset), Decimal("0"))
        return balance

    def adjust_and_place_order(self, exchange: str, trading_pair: str, order_type: OrderType, is_maker: bool,
                               order_side,
                               amount: Decimal, price: Optional[Decimal] = Decimal("nan")):
        order = OrderCandidate(trading_pair=trading_pair,
                               order_type=order_type,
                               is_maker=is_maker,
                               order_side=order_side,
                               amount=amount,
                               price=self.connectors[exchange].get_price(trading_pair=self.TRADING_PAIR, is_buy=True))
        order_adjusted = self.connectors[exchange].budget_checker.adjust_candidate(order)
        order_id = pd.NA
        if order_adjusted.amount > Decimal("0"):
            if order_side == TradeType.SELL:
                order_id = self.sell(
                    exchange,
                    order_adjusted.trading_pair,
                    order_adjusted.amount,
                    order_adjusted.order_type,
                    order_adjusted.price)
            elif order_side == TradeType.BUY:
                order_id = self.buy(
                    exchange,
                    order_adjusted.trading_pair,
                    order_adjusted.amount,
                    order_adjusted.order_type,
                    order_adjusted.price)
        else:
            self.logger().info("NOT ENOUGH BALANCE")
        return order_id

    def did_complete_buy_order(self, event: BuyOrderCompletedEvent):
        """
        Method called when the connector notifies a buy order has been completed (fully filled)
        """
        amount = round(event.base_asset_amount, 2)
        price = round(event.quote_asset_amount / event.base_asset_amount, 2)
        tp_price = round(price * Decimal(1 + self.TAKE_PROFIT), 2)
        sl_price = round(price * Decimal(1 - self.STOP_LOSS), 2)

        self.signals.loc[self.signals["open_order_id"] == event.order_id, ["amount", "price", "tp_price", "sl_price"]] = [
            amount, price, tp_price, sl_price]
        self.logger().info(f"The buy order {event.order_id} has been completed")

    def did_complete_sell_order(self, event: SellOrderCompletedEvent):
        """
        Method called when the connector notifies a sell order has been completed (fully filled)
        """
        amount = round(event.base_asset_amount, 2)
        price = round(event.quote_asset_amount / event.base_asset_amount, 2)
        tp_price = pd.NA
        sl_price = pd.NA

        self.signals.loc[self.signals["open_order_id"] == event.order_id, ["amount", "price", "tp_price", "sl_price"]] = [
            amount, price, tp_price, sl_price]
        self.logger().info(f"The sell order {event.order_id} has been completed")
