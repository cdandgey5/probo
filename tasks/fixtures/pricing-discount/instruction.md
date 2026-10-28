A 100 percent discount should bring a price down to zero, but
`DiscountCalculator.applyDiscount(200L, 100)` returns 2.

Fix the bug so that a full discount yields zero. Prices are integer cents and
the discount is a percentage that callers may pass out of range: a negative
percentage must still be treated as zero, and every existing test must keep
passing.
