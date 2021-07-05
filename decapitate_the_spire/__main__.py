import sys

from decapitate_the_spire.decapitate_the_spire import fib

if __name__ == "__main__":
    n = int(sys.argv[1])
    print(fib(n))
