package com.example.pricing

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class DiscountCalculatorTest {

    @Test
    fun halfDiscountHalvesPrice() {
        assertEquals(100L, DiscountCalculator.applyDiscount(200L, 50))
    }

    @Test
    fun zeroDiscountKeepsPrice() {
        assertEquals(200L, DiscountCalculator.applyDiscount(200L, 0))
    }

    @Test
    fun negativePercentIsClampedToZero() {
        assertEquals(200L, DiscountCalculator.applyDiscount(200L, -5))
    }

    @Test
    fun negativePriceIsRejected() {
        assertFailsWith<IllegalArgumentException> {
            DiscountCalculator.applyDiscount(-1L, 10)
        }
    }
}
