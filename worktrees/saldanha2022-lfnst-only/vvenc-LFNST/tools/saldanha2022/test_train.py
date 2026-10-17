import unittest
import random
import train

class TrainingTests(unittest.TestCase):
    def test_leakage(self):
        for value in ['I:/Sequences360/ERP14/a.csv', 'ERP14', 'i:\\sequences360\\ERP14'] + train.EXCLUDED_NAMES:
            with self.assertRaises(ValueError): train.check_source(value)
        with self.assertRaises(ValueError): train.split_rows([{'sequence':'a'}], ['a'], ['a'])

    def test_balance_determinism(self):
        rows = [dict(sequence=s,poc=str(p),width='8',height='8',qp='32',label=str(c),currCost=str(i))
                for s in ['a','b'] for p in range(2) for c in range(2) for i in range(20 if c else 3)]
        selected = train.balanced_sample(rows, 20, 17)
        random.Random(99).shuffle(rows)
        self.assertEqual(selected, train.balanced_sample(rows,20,17))
        self.assertEqual(len(selected),20)
        self.assertEqual(sum(int(x['label']) for x in selected),10)

    def test_boundaries(self):
        nodes = [(0,0,1.5,1,2,0.3,0.5,0.5),(1,-1,0,-1,-1,0,1,0),(2,-1,0,-1,-1,0,0,1)]
        self.assertEqual(train.predict(nodes,[1.499]),[1,0])
        self.assertEqual(train.predict(nodes,[1.5]),[0,1])
        self.assertEqual(train.predict(nodes,[float('nan')]),[0.3,0.7])

if __name__ == '__main__': unittest.main()
