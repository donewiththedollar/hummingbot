import math

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
    BASE = "BTC"
    QUOTE = "USDT"
    TRADING_PAIR = combine_to_hb_trading_pair(BASE, QUOTE)
    EXCHANGE = "binance_paper_trade"
    #: Define markets to instruct Hummingbot to create connectors on the exchanges and markets you need
    markets = {EXCHANGE: {TRADING_PAIR}}
    #: max quantity of tokens un base asset
    MAX_POSITION = 1
    #: min quantity of tokens un base asset
    MIN_POSITION = 0
    #: order size for each signal
    ORDER_SIZE = 0.1
    #: min order size
    MIN_ORDER_SIZE = 0.02
    #: The last time the strategy looks for a new signal
    TIME_BETWEEN_SIGNALS = 10
    #: threshold to accept the signal and increase the position
    ENTRY_THRESHOLD = 0.7
    #: threshold to reduce the position
    EXIT_THRESHOLD = 0.3
    #: take profit in percentage (1% = 0.01)
    TAKE_PROFIT = 0.03
    #: stop loss in percentage (1% = 0.01)
    STOP_LOSS = 0.01
    #: last signal time to evaluate with time between signals
    last_signal_time = 0
    #: signal stats
    signals = pd.DataFrame(columns=["signal", "price", "order_id", "tp_price", "sl_price"])

    def on_tick(self):
        # Check if it is time to get a new signal
        if self.last_signal_time < (self.current_timestamp - self.TIME_BETWEEN_SIGNALS):
            self.last_signal_time = self.current_timestamp
            # get the signal
            signal = self.get_signal()
            amount_base = max(self.connectors[self.EXCHANGE].get_balance(self.BASE), Decimal("0"))
            if signal > self.ENTRY_THRESHOLD:
                self.logger().info(f"Signal > ENTRY THRESHOLD {self.ENTRY_THRESHOLD}")
                if amount_base < self.MAX_POSITION or math.isclose(amount_base, self.MAX_POSITION, rel_tol=self.MIN_ORDER_SIZE):
                    amount_to_buy = min(self.ORDER_SIZE, self.MAX_POSITION - amount_base)

                    order = OrderCandidate(trading_pair=self.TRADING_PAIR,
                                           order_type=OrderType.MARKET,
                                           is_maker=True,
                                           order_side=TradeType.BUY,
                                           amount=Decimal(amount_to_buy),
                                           price=Decimal("0"))
                    order_adjusted = self.connectors[self.EXCHANGE].budget_checker.adjust_candidate(order)
                    if order_adjusted.amount > Decimal("0"):
                        price = self.connectors[self.EXCHANGE].get_price(self.TRADING_PAIR, is_buy=True)
                        tp_price = price * (1 + Decimal(self.TAKE_PROFIT))
                        sl_price = price * (1 - Decimal(self.STOP_LOSS))
                        order_id = self.buy(
                            self.EXCHANGE,
                            order_adjusted.trading_pair,
                            order_adjusted.amount,
                            order_adjusted.order_type,
                            order_adjusted.price)
                        self.signals.loc[len(self.signals.index)] = [signal, price, order_id, tp_price, sl_price]
                    else:
                        self.signals.loc[len(self.signals.index)] = [signal, pd.NA, pd.NA, pd.NA, pd.NA]
                        self.logger().info("NOT ENOUGH BALANCE")
            elif signal < self.EXIT_THRESHOLD:
                self.logger().info(f"Signal < EXIT THRESHOLD {self.EXIT_THRESHOLD} ==> TRY TO DECREASE POSITION")
                if amount_base > self.MIN_POSITION or math.isclose(amount_base, self.MIN_POSITION, rel_tol=self.MIN_ORDER_SIZE):
                    amount_to_sell = min(self.ORDER_SIZE, amount_base - self.MIN_POSITION)
                    order = OrderCandidate(trading_pair=self.TRADING_PAIR,
                                           order_type=OrderType.MARKET,
                                           is_maker=True,
                                           order_side=TradeType.SELL,
                                           amount=Decimal(amount_to_sell),
                                           price=Decimal("nan"))
                    order_adjusted = self.connectors[self.EXCHANGE].budget_checker.adjust_candidate(order)
                    if order_adjusted.amount > Decimal("0"):
                        price = self.connectors[self.EXCHANGE].get_price(self.TRADING_PAIR, is_buy=False)
                        order_id = self.sell(
                            self.EXCHANGE,
                            order_adjusted.trading_pair,
                            order_adjusted.amount,
                            order_adjusted.order_type,
                            order_adjusted.price)
                        self.signals.loc[len(self.signals.index)] = [signal, price, order_id, pd.NA, pd.NA]
                    else:
                        self.signals.loc[len(self.signals.index)] = [signal, pd.NA, pd.NA, pd.NA, pd.NA]
                        self.logger().info("NOT ENOUGH BALANCE")

            else:
                self.signals.loc[len(self.signals.index)] = [signal, pd.NA, pd.NA, pd.NA, pd.NA]

    def get_signal(self):
        return random.normal(loc=0.6, scale=0.25)

    def did_complete_buy_order(self, event: BuyOrderCompletedEvent):
        """
        Method called when the connector notifies a buy order has been completed (fully filled)
        """
        self.logger().info(f"The buy order {event.order_id} has been completed")

    def did_complete_sell_order(self, event: SellOrderCompletedEvent):
        """
        Method called when the connector notifies a sell order has been completed (fully filled)
        """
        self.logger().info(f"The sell order {event.order_id} has been completed")

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

        lines.extend(["", "  Signals:"] + ["    " + line for line in self.signals[["signal", "order_id", "price"]].to_string(index=False).split("\n")])
        warning_lines.extend(self.balance_warning(self.get_market_trading_pair_tuples()))
        if len(warning_lines) > 0:
            lines.extend(["", "*** WARNINGS ***"] + warning_lines)
        return "\n".join(lines)
