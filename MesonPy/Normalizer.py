import numbers

class NormalizerManager:
    def __init__(self, app):
        self._normalizers   = []
        self._denormalizers = []
        
        self.addNormalizer(lambda otype: otype is Exception, lambda obj: str(obj))

    def addDenormalizer(self, applicableFunc, denormalizerFunc):
        self._denormalizers.insert(0, (applicableFunc, denormalizerFunc))
        return self

    def addNormalizer(self, applicableFunc, normalizeFunc):
        self._normalizers.insert(0, (applicableFunc, normalizeFunc))
        return self

    def hasNormalizer(self, node):
        for applicableFunc in map(lambda el: el[0], self._normalizers):
            if applicableFunc(node): return True
        return False
    
    def getNormalizer(self, oType):
         for applicableFunc, normalizerFunc in self._normalizers:
            if applicableFunc(oType): return normalizerFunc    
    
    def denormalize(self, node):
        return node

    def normalize(self, node):
        oType = type(node)
        if type(node) is list:
            return [self.normalize(element) for element in node]
        elif type(node) is dict:
            return {key: self.normalize(element) for key, element in node.items()}
        elif isinstance(node, numbers.Number):
            return node
        elif isinstance(node, str):
            return node
        elif self.hasNormalizer(oType):
            depth1NormalizedDict = self.getNormalizer(oType)(node)
            
            normalizedObject     = {
                '__obj__': oType.__name__,
                '__content__': self.normalize(depth1NormalizedDict)
            }
            
            return normalizedObject
        else:
            ValueError('Cannot normalize current object of type {}, please register a normalizer for this type.'.format(oType.__name__))