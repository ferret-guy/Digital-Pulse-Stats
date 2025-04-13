from saleae.range_measurements import DigitalMeasurer
import math

class ExtendedDigitalMeasurer(DigitalMeasurer):
    """
    Collects:
      - Positive pulse widths
      - Negative pulse widths
      - Duty cycles
      - Frequency stats
    Then returns min, max, and mean for each category.
    """

    # All the measurements we may return
    supported_measurements = [
        "posPulseWidthMean", "posPulseWidthMin", "posPulseWidthMax",
        "negPulseWidthMean", "negPulseWidthMin", "negPulseWidthMax",

        "dutyMean", "dutyMin", "dutyMax",

        "freqMean", "freqMin", "freqMax"
    ]

    def __init__(self, requested_measurements):
        super().__init__(requested_measurements)

        # Pulse lists
        self.pos_pulse_widths = []  # rising->falling
        self.neg_pulse_widths = []  # falling->rising

        # For computing duty cycle & frequency, we track each "cycle":
        # Rising -> next Rising is one cycle. 
        # We'll also track how much of that cycle was high, to compute duty.
        self.cycle_periods = []
        self.cycle_high_times = []

        # States to track while parsing data
        self.last_time = None
        self.last_bitstate = None

        # For partial pulses
        self.rising_time = None
        self.falling_time = None

        # For cycle measurement
        self.last_rising_time = None  # Start of current cycle

    def process_data(self, data):
        """
        data is an iterable of (time, bitstate).
        The first tuple is the start state at the measurement range,
        then each subsequent tuple is a transition.
        """
        for t, bitstate in data:
            # If first iteration, just record the state
            if self.last_bitstate is None:
                self.last_bitstate = bitstate
                self.last_time = t
                # If we start high, let's remember that as if it was a "rising" 
                # so a partial pulse can be measured
                if bitstate:
                    self.rising_time = t
                    self.last_rising_time = t
                continue

            # Identify transitions:
            # 1) Rising edge: (low->high)
            if (not self.last_bitstate) and bitstate:
                # End any negative pulse in progress
                if self.falling_time is not None:
                    neg_width = float(t - self.falling_time)
                    self.neg_pulse_widths.append(neg_width)
                    self.falling_time = None

                # Start positive pulse
                self.rising_time = t

                # If we had a previous cycle, the new rising edge means:
                #   last_rising_time -> this rising is one cycle
                if self.last_rising_time is not None:
                    cycle_period = float(t - self.last_rising_time)
                    self.cycle_periods.append(cycle_period)

                    # We also compute how much of that cycle was high.
                    # If the signal was high from last_rising_time -> falling_time,
                    # we need to accumulate it. However, let's do it more simply:
                    # We'll store each cycle's "high time" separately, measured 
                    # from the partial pulses that began after the last rising.
                    # Because of boundary conditions, we need to carefully measure 
                    # each portion that was high within that cycle.
                    # For simplicity in this example, let's assume the entire "pos_pulse_widths"
                    # that started after last_rising_time belongs to this cycle.
                    # This is not perfect for signals that have multiple pulses per cycle,
                    # but it works for typical single-pulse-per-cycle waveforms.
                    
                    # We'll approximate the last positive pulse as the one that ended 
                    # after last_rising_time. That means the last entry in self.pos_pulse_widths 
                    # might belong to that cycle if it started after last_rising_time. 
                    # We'll store an array of "cycle high times" in parallel with cycle_periods.
                    
                    # For a robust approach, store partial pulses with their start times 
                    # and decide which cycle they belong to. For simplicity, let's do the easy path:
                    
                    # We'll do nothing here, and compute duty cycle after measure() by scanning pulses.
                    pass
                
                # Mark the start of a new cycle
                self.last_rising_time = t

            # 2) Falling edge: (high->low)
            elif self.last_bitstate and (not bitstate):
                # End positive pulse
                if self.rising_time is not None:
                    pos_width = float(t - self.rising_time)
                    self.pos_pulse_widths.append(pos_width)
                    self.rising_time = None

                # Start negative pulse
                self.falling_time = t

            # Remember last bit state/time for next iteration
            self.last_bitstate = bitstate
            self.last_time = t

    def measure(self):
        """
        Called once after all data has been processed.
        We'll compute min, max, mean for each of the requested measurements.
        Then return them in a dictionary keyed by metric name.
        """
        results = {}

        # If the user wants any positive pulse metrics, compute them
        if any(k in self.requested_measurements for k in [
            "posPulseWidthMean", "posPulseWidthMin", "posPulseWidthMax"]):
            
            if self.pos_pulse_widths:
                pos_mean = sum(self.pos_pulse_widths) / len(self.pos_pulse_widths)
                pos_min = min(self.pos_pulse_widths)
                pos_max = max(self.pos_pulse_widths)
            else:
                pos_mean = pos_min = pos_max = 0.0

            if "posPulseWidthMean" in self.requested_measurements:
                results["posPulseWidthMean"] = pos_mean
            if "posPulseWidthMin" in self.requested_measurements:
                results["posPulseWidthMin"] = pos_min
            if "posPulseWidthMax" in self.requested_measurements:
                results["posPulseWidthMax"] = pos_max

        # Negative pulses
        if any(k in self.requested_measurements for k in [
            "negPulseWidthMean", "negPulseWidthMin", "negPulseWidthMax"]):
            
            if self.neg_pulse_widths:
                neg_mean = sum(self.neg_pulse_widths) / len(self.neg_pulse_widths)
                neg_min = min(self.neg_pulse_widths)
                neg_max = max(self.neg_pulse_widths)
            else:
                neg_mean = neg_min = neg_max = 0.0

            if "negPulseWidthMean" in self.requested_measurements:
                results["negPulseWidthMean"] = neg_mean
            if "negPulseWidthMin" in self.requested_measurements:
                results["negPulseWidthMin"] = neg_min
            if "negPulseWidthMax" in self.requested_measurements:
                results["negPulseWidthMax"] = neg_max

        # Frequency & Duty Cycle
        # ------------------------------------------------------------
        # We'll do a simple approach for frequency & duty cycle by pairing 
        # up the measured cycle periods with the positive pulse widths 
        # that fell entirely inside that cycle.
        # 
        # For a real signal with multiple pulses per cycle or partial edges 
        # at the measurement boundary, you may need more robust logic.

        # 1) If we have cycle_periods from rising->rising
        #    We'll attempt to match each cycle to exactly one pos_pulse_width
        #    that started after the cycle's rising edge and ended before 
        #    the next rising edge.
        
        duty_values = []
        freq_values = []
        
        # We'll just walk through cycle_periods. For each cycle period:
        #   we find a corresponding positive pulse in self.pos_pulse_widths 
        #   that occurred in that interval, if any.
        
        # This is a naive approach: if the signal is truly 50% square wave, 
        # pos_pulse_widths[i] should correspond to cycle_periods[i].
        # If pulses are more complex, this logic might not align perfectly.
        
        # We'll do a quick approach: assume they line up in order of detection.
        # So we pair them in index order.
        
        cycle_count = min(len(self.cycle_periods), len(self.pos_pulse_widths))
        for i in range(cycle_count):
            T_period = self.cycle_periods[i]
            T_high   = self.pos_pulse_widths[i]
            
            if T_period > 0:
                duty = T_high / T_period
                freq = 1.0 / T_period
            else:
                duty = 0.0
                freq = 0.0
            duty_values.append(duty)
            freq_values.append(freq)

        if any(k in self.requested_measurements for k in ["dutyMean", "dutyMin", "dutyMax"]):
            if duty_values:
                duty_mean = sum(duty_values) / len(duty_values)
                duty_min = min(duty_values)
                duty_max = max(duty_values)
            else:
                duty_mean = duty_min = duty_max = 0.0

            if "dutyMean" in self.requested_measurements:
                results["dutyMean"] = duty_mean
            if "dutyMin" in self.requested_measurements:
                results["dutyMin"] = duty_min
            if "dutyMax" in self.requested_measurements:
                results["dutyMax"] = duty_max

        if any(k in self.requested_measurements for k in ["freqMean", "freqMin", "freqMax"]):
            if freq_values:
                freq_mean = sum(freq_values) / len(freq_values)
                freq_min = min(freq_values)
                freq_max = max(freq_values)
            else:
                freq_mean = freq_min = freq_max = 0.0

            if "freqMean" in self.requested_measurements:
                results["freqMean"] = freq_mean
            if "freqMin" in self.requested_measurements:
                results["freqMin"] = freq_min
            if "freqMax" in self.requested_measurements:
                results["freqMax"] = freq_max

        return results
