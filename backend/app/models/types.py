from sqlalchemy import BigInteger, Integer

BigInt = BigInteger().with_variant(Integer, "sqlite")
